from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from qdrant_client import models

from app.config import settings
from app.core.context import EngineContext, get_engine_context
from app.core.retrieval import build_filter
from app.schemas.documents import (
    DeleteDocumentResponse,
    DocumentItem,
    DocumentListResponse,
)

router = APIRouter(tags=["documents"])


def group_documents(points: list[Any]) -> list[DocumentItem]:
    """Collapse chunk points into one document row per doc_id."""

    grouped: dict[str, DocumentItem] = {}
    for point in points:
        payload = point.payload or {}
        doc_id = payload.get("doc_id")
        if not doc_id:
            continue
        key = str(doc_id)
        acl_raw = payload.get("acl") or []
        acl = [str(item) for item in acl_raw] if isinstance(acl_raw, list) else [str(acl_raw)]

        item = grouped.get(key)
        if item is None:
            item = DocumentItem(
                doc_id=key,
                source=payload.get("source") or payload.get("file_name"),
                version=payload.get("version"),
                doc_type=payload.get("doc_type"),
                effective_date=payload.get("effective_date"),
                is_current=bool(payload.get("is_current", True)),
                acl=sorted(set(acl)),
                chunks=0,
            )
            grouped[key] = item
        else:
            item.acl = sorted(set(item.acl) | set(acl))
        item.chunks += 1

    return sorted(
        grouped.values(),
        key=lambda item: (item.source or "", item.version or "", item.doc_id),
    )


@router.get("/documents", response_model=DocumentListResponse, summary="列出知识库文档")
async def list_documents(
    request: Request,
    version: str | None = Query(None, max_length=100),
    doc_type: str | None = Query(None, max_length=100),
    is_current: bool | None = Query(None),
    max_points: int = Query(5000, ge=1, le=50000),
    context: EngineContext = Depends(get_engine_context),
) -> DocumentListResponse:
    filters: dict[str, Any] = {"is_current": is_current}
    if version:
        filters["version"] = version
    if doc_type:
        filters["doc_type"] = [doc_type]

    scroll_filter = build_filter(context.tenant_id, context.acl, filters)
    client = request.app.state.retrieval.client
    points: list[Any] = []
    offset = None
    scanned = 0

    while scanned < max_points:
        batch, offset = await client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=scroll_filter,
            limit=min(256, max_points - scanned),
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not batch:
            break
        points.extend(batch)
        scanned += len(batch)
        if offset is None:
            break

    return DocumentListResponse(
        items=group_documents(points),
        scanned_chunks=scanned,
        truncated=offset is not None,
    )


@router.delete(
    "/documents/{doc_id}",
    response_model=DeleteDocumentResponse,
    summary="删除文档及其全部 chunk",
)
async def delete_document(
    request: Request,
    doc_id: str,
    context: EngineContext = Depends(get_engine_context),
) -> DeleteDocumentResponse:
    key = doc_id.strip()
    if not key or len(key) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="非法 doc_id",
        )

    delete_filter = build_filter(
        context.tenant_id,
        context.acl,
        {"is_current": None},
    )
    delete_filter.must.append(
        models.FieldCondition(
            key="doc_id",
            match=models.MatchValue(value=key),
        )
    )

    client = request.app.state.retrieval.client
    counted = await client.count(
        collection_name=settings.qdrant_collection,
        count_filter=delete_filter,
        exact=True,
    )
    if counted.count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document not found",
        )

    await client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=delete_filter,
        wait=True,
    )
    await request.app.state.rag.clear_cache()

    return DeleteDocumentResponse(doc_id=key, deleted_chunks=counted.count)
