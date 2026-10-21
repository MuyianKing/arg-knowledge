from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterable
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import jieba
from qdrant_client import QdrantClient, models

from app.config import settings
from app.ingest.chunking import chunk_documents
from app.ingest.parsers import doc_type_for, load_documents


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bm25_text(text: str) -> str:
    return " ".join(jieba.cut(text))


def _report(
    progress: Callable[[str, int, int], None] | None,
    stage: str,
    current: int,
    total: int,
) -> None:
    if progress is not None:
        progress(stage, current, total)


def preview_chunks(path: Path, limit: int = 100) -> dict[str, Any]:
    """Parse and chunk without loading models or writing to Qdrant."""

    documents = load_documents(path)
    nodes = chunk_documents(documents)
    items: list[dict[str, Any]] = []
    for index, node in enumerate(nodes[:limit]):
        text = (node.get_content() or "").strip()
        file_path = Path(
            node.metadata.get("file_path") or node.metadata.get("file_name") or "unknown"
        )
        items.append(
            {
                "index": index,
                "source": file_path.name,
                "doc_type": doc_type_for(file_path),
                "page": node.metadata.get("page_label") or node.metadata.get("page"),
                "chars": len(text),
                "text": text,
            }
        )
    return {
        "documents": len(documents),
        "chunks": len(nodes),
        "items": items,
    }


class IngestPipeline:
    def __init__(self) -> None:
        self._embedder = None
        self._bm25 = None
        self._client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=60,
        )

    def attach_models(self, embedder, bm25) -> None:
        """Reuse models already loaded by the retrieval service (one copy per process)."""

        self._embedder = embedder
        self._bm25 = bm25

    def _ensure_models(self) -> None:
        if self._embedder is not None:
            return
        import torch
        from fastembed.sparse.bm25 import Bm25
        from FlagEmbedding import BGEM3FlagModel

        self._embedder = BGEM3FlagModel(
            str(settings.bge_m3_path),
            use_fp16=torch.cuda.is_available(),
        )
        self._bm25 = Bm25(
            model_name="Qdrant/bm25",
            specific_model_path=str(settings.bm25_model_path),
            disable_stemmer=True,
        )

    def ingest(
        self,
        path: Path,
        *,
        tenant_id: str,
        acl: Iterable[str],
        version: str,
        effective_date: date | None = None,
        doc_type: str = "auto",
        batch_size: int | None = None,
        dry_run: bool = False,
        progress: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, int]:
        acl_list = list(acl)
        _report(progress, "parsing", 0, 0)
        documents = load_documents(path)
        _report(progress, "parsing", len(documents), len(documents))
        _report(progress, "chunking", 0, 0)
        nodes = chunk_documents(documents)
        _report(progress, "chunking", len(nodes), len(nodes))

        if not nodes:
            _report(progress, "completed", 0, 0)
            return {"documents": len(documents), "chunks": 0, "upserted": 0}

        effective = datetime.combine(
            effective_date or date.today(),
            time.min,
        ).isoformat()
        batch_size = batch_size or settings.ingest_batch_size
        points: list[models.PointStruct] = []
        chunk_count = 0

        for index, node in enumerate(nodes):
            text = (node.get_content() or "").strip()
            if not text:
                continue

            file_path = Path(
                node.metadata.get("file_path") or node.metadata.get("file_name") or "unknown"
            )
            doc_key = f"{tenant_id}:{file_path.as_posix()}:{version}"
            doc_id = hashlib.sha1(doc_key.encode("utf-8")).hexdigest()[:16]
            content_hash = _sha256(text)
            chunk_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{doc_id}:{index}:{content_hash}",
                )
            )
            resolved_doc_type = doc_type if doc_type != "auto" else doc_type_for(file_path)
            page_label = node.metadata.get("page_label") or node.metadata.get("page") or None

            payload: dict[str, Any] = {
                "text": text,
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "tenant_id": tenant_id,
                "acl": acl_list,
                "doc_type": resolved_doc_type,
                "version": version,
                "is_current": True,
                "source": file_path.name,
                "file_name": file_path.name,
                "page_label": str(page_label) if page_label is not None else None,
                "effective_date": effective,
                "chunk_index": index,
                "content_hash": content_hash,
            }
            payload = {key: value for key, value in payload.items() if value is not None}
            chunk_count += 1

            if not dry_run:
                points.append(
                    models.PointStruct(
                        id=chunk_id,
                        vector={
                            "dense": [],  # filled below
                            "sparse": models.SparseVector(indices=[], values=[]),
                        },
                        payload=payload,
                    )
                )

        if dry_run:
            _report(progress, "completed", chunk_count, chunk_count)
            return {"documents": len(documents), "chunks": chunk_count, "upserted": 0}

        _report(progress, "loading_models", 0, 0)
        self._ensure_models()
        texts = [point.payload["text"] for point in points]
        _report(progress, "embedding", 0, len(texts))

        dense_vectors = []
        sparse_vectors = []
        for start in range(0, len(texts), batch_size):
            batch_texts = texts[start : start + batch_size]
            dense_batch = self._embedder.encode(
                batch_texts,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
                max_length=settings.embedding_max_length,
                batch_size=batch_size,
            )["dense_vecs"]
            sparse_batch = list(self._bm25.embed([_bm25_text(text) for text in batch_texts]))
            dense_vectors.extend(dense_batch)
            sparse_vectors.extend(sparse_batch)
            _report(progress, "embedding", len(dense_vectors), len(texts))

        for point, dense, sparse in zip(points, dense_vectors, sparse_vectors):
            point.vector = {
                "dense": dense.tolist(),
                "sparse": models.SparseVector(
                    indices=sparse.indices.tolist(),
                    values=sparse.values.tolist(),
                ),
            }

        upserted = 0
        _report(progress, "upserting", 0, len(points))
        for start in range(0, len(points), batch_size):
            batch = points[start : start + batch_size]
            self._client.upsert(
                collection_name=settings.qdrant_collection,
                points=batch,
                wait=True,
            )
            upserted += len(batch)
            _report(progress, "upserting", upserted, len(points))
            print(f"upserted {upserted}/{len(points)}")

        _report(progress, "completed", len(points), len(points))
        return {
            "documents": len(documents),
            "chunks": len(points),
            "upserted": upserted,
        }

    def close(self) -> None:
        self._client.close()
