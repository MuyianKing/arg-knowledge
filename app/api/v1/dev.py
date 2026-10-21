"""Local debugging endpoints. Only registered when DEV_TOOLS_ENABLED=true.

These endpoints let the bundled web console (web/) configure the LLM at runtime,
inspect retrieval, and upload documents without using the CLI. They are not part
of the public engine contract and must never be enabled in production.
"""

from __future__ import annotations

import asyncio
import shutil
import time
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.config import settings
from app.core.context import EngineContext, get_engine_context
from app.ingest.parsers import SUPPORTED_EXTENSIONS
from app.schemas.dev import (
    IngestResponse,
    LLMConfigResponse,
    LLMConfigUpdate,
    LLMTestResponse,
    RetrievedChunk,
    RetrieveRequest,
    RetrieveResponse,
)

router = APIRouter(prefix="/dev", tags=["dev"])

_UPLOAD_CHUNK = 1024 * 1024


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "").name.strip()
    if not name or name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少文件名",
        )
    if len(name) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名过长",
        )
    if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型，允许：{allowed}",
        )
    return name


async def _save_upload(file: UploadFile, target: Path, max_bytes: int) -> None:
    size = 0
    handle = await asyncio.to_thread(target.open, "wb")
    try:
        while chunk := await file.read(_UPLOAD_CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"文件超过 {settings.max_upload_mb} MB 限制",
                )
            await asyncio.to_thread(handle.write, chunk)
    finally:
        await asyncio.to_thread(handle.close)
        await file.close()


@router.get("/llm", response_model=LLMConfigResponse, summary="查看当前 LLM 配置")
async def get_llm_config(request: Request) -> LLMConfigResponse:
    return LLMConfigResponse(**request.app.state.llm.describe())


@router.put("/llm", response_model=LLMConfigResponse, summary="运行时更新 LLM 配置")
async def update_llm_config(body: LLMConfigUpdate, request: Request) -> LLMConfigResponse:
    described = await request.app.state.llm.reconfigure(
        **body.model_dump(exclude_none=True),
    )
    return LLMConfigResponse(**described)


@router.post("/llm/test", response_model=LLMTestResponse, summary="测试 LLM 连通性")
async def test_llm(request: Request) -> LLMTestResponse:
    result = await request.app.state.llm.test_connection()
    return LLMTestResponse(**result)


@router.post("/retrieve", response_model=RetrieveResponse, summary="仅检索（不生成）")
async def retrieve(
    body: RetrieveRequest,
    request: Request,
    context: EngineContext = Depends(get_engine_context),
) -> RetrieveResponse:
    started = time.perf_counter()
    filters = body.filters.model_dump(exclude_none=True) if body.filters else {}
    retrieval = request.app.state.retrieval

    try:
        retrieval_started = time.perf_counter()
        candidates = await retrieval.search(
            body.query,
            context.tenant_id,
            context.acl,
            filters,
        )
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

        rerank_started = time.perf_counter()
        chunks = await retrieval.rerank(body.query, candidates, body.top_k or settings.top_k)
        rerank_ms = int((time.perf_counter() - rerank_started) * 1000)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"检索失败：{type(exc).__name__}: {exc}"[:500],
        ) from exc

    return RetrieveResponse(
        chunks=[
            RetrievedChunk(
                id=chunk.id,
                score=chunk.score,
                source=chunk.source,
                page=chunk.page,
                version=chunk.version,
                text=chunk.text,
            )
            for chunk in chunks
        ],
        candidates=len(candidates),
        retrieval_ms=retrieval_ms,
        rerank_ms=rerank_ms,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


@router.post("/ingest", response_model=IngestResponse, summary="上传并同步入库")
async def ingest(
    request: Request,
    file: UploadFile = File(...),
    version: str = Form("v1"),
    doc_type: str = Form("auto"),
    effective_date: str | None = Form(None),
    dry_run: bool = Form(False),
    context: EngineContext = Depends(get_engine_context),
) -> IngestResponse:
    started = time.perf_counter()
    pipeline = request.app.state.ingest
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="入库流水线未初始化，请以 DEV_TOOLS_ENABLED=true 启动引擎",
        )

    name = _safe_filename(file.filename)
    try:
        effective = date.fromisoformat(effective_date) if effective_date else None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="effective_date 必须是 YYYY-MM-DD",
        ) from exc

    target_dir = Path(settings.upload_dir) / uuid.uuid4().hex
    await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
    target = target_dir / name

    try:
        await _save_upload(file, target, settings.max_upload_mb * 1024 * 1024)

        if not dry_run:
            # Reuse the embedding models already loaded by the retrieval service.
            retrieval = request.app.state.retrieval
            await retrieval.ensure_models()
            pipeline.attach_models(retrieval.embedder, retrieval.bm25)

        async with request.app.state.ingest_lock:
            result = await asyncio.to_thread(
                pipeline.ingest,
                target,
                tenant_id=context.tenant_id,
                acl=context.acl,
                version=version,
                effective_date=effective,
                doc_type=doc_type,
                dry_run=dry_run,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"入库失败：{type(exc).__name__}: {exc}"[:500],
        ) from exc
    finally:
        await asyncio.to_thread(shutil.rmtree, target_dir, ignore_errors=True)

    return IngestResponse(
        filename=name,
        tenant_id=context.tenant_id,
        acl=list(context.acl),
        version=version,
        doc_type=doc_type,
        dry_run=dry_run,
        documents=result.get("documents", 0),
        chunks=result.get("chunks", 0),
        upserted=result.get("upserted", 0),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
