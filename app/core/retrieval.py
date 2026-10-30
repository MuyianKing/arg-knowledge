from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import jieba
from qdrant_client import AsyncQdrantClient, models

from app.config import settings


@dataclass
class Chunk:
    id: str
    text: str
    source: str | None
    page: str | None
    version: str | None
    score: float = 0.0
    payload: dict[str, Any] | None = None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def build_filter(
    tenant_id: str,
    acl: tuple[str, ...],
    filters: dict[str, Any] | None,
) -> models.Filter:
    filters = filters or {}
    must: list[models.Condition] = [
        models.FieldCondition(
            key="tenant_id",
            match=models.MatchValue(value=tenant_id),
        ),
    ]

    is_current = filters.get("is_current", True)
    if is_current is not None:
        must.append(
            models.FieldCondition(
                key="is_current",
                match=models.MatchValue(value=bool(is_current)),
            )
        )

    doc_types = _as_list(filters.get("doc_type"))
    if doc_types:
        must.append(
            models.FieldCondition(
                key="doc_type",
                match=models.MatchAny(any=doc_types),
            )
        )

    version = filters.get("version")
    if version:
        must.append(
            models.FieldCondition(
                key="version",
                match=models.MatchValue(value=str(version)),
            )
        )

    effective_from = filters.get("effective_date_from")
    if effective_from:
        must.append(
            models.FieldCondition(
                key="effective_date",
                range=models.DatetimeRange(gte=effective_from),
            )
        )

    should: list[models.Condition] = []
    if acl:
        should.append(
            models.FieldCondition(
                key="acl",
                match=models.MatchAny(any=list(acl)),
            )
        )

    return models.Filter(must=must, should=should or None)


class RetrievalService:
    def __init__(self) -> None:
        self._client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
        )
        self._embedder = None
        self._reranker = None
        self._bm25 = None
        self._load_lock = asyncio.Lock()

    @property
    def client(self) -> AsyncQdrantClient:
        return self._client

    @property
    def embedder(self):
        return self._embedder

    @property
    def bm25(self):
        return self._bm25

    @property
    def is_loaded(self) -> bool:
        return self._embedder is not None and self._reranker is not None and self._bm25 is not None

    async def ensure_models(self) -> None:
        """Load embedding models once so ingestion can reuse them."""

        await self._ensure_models()

    async def _ensure_models(self) -> None:
        if self._embedder is not None:
            return
        async with self._load_lock:
            if self._embedder is not None:
                return
            await asyncio.to_thread(self._load_models)

    def _load_models(self) -> None:
        import torch
        from fastembed.sparse.bm25 import Bm25
        from FlagEmbedding import BGEM3FlagModel, FlagReranker

        use_fp16 = torch.cuda.is_available()
        self._embedder = BGEM3FlagModel(
            str(settings.bge_m3_path),
            use_fp16=use_fp16,
        )
        self._reranker = FlagReranker(
            str(settings.bge_reranker_path),
            use_fp16=use_fp16,
        )
        self._bm25 = Bm25(
            model_name="Qdrant/bm25",
            specific_model_path=str(settings.bm25_model_path),
            disable_stemmer=True,
        )

    def _embed_query(self, query: str) -> tuple[list[float], list[int], list[float]]:
        dense_output = self._embedder.encode(
            [query],
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
            max_length=settings.embedding_max_length,
        )
        dense = dense_output["dense_vecs"][0].tolist()

        tokens = " ".join(jieba.cut(query))
        sparse = next(iter(self._bm25.embed([tokens])))
        return dense, sparse.indices.tolist(), sparse.values.tolist()

    async def search(
        self,
        query: str,
        tenant_id: str,
        acl: tuple[str, ...],
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        await self._ensure_models()
        dense, sparse_indices, sparse_values = await asyncio.to_thread(self._embed_query, query)
        query_filter = build_filter(tenant_id, acl, filters)
        search_params = models.SearchParams(
            quantization=models.QuantizationSearchParams(
                ignore=False,
                rescore=True,
                oversampling=2.0,
            ),
            hnsw_ef=128,
        )

        result = await self._client.query_points(
            collection_name=settings.qdrant_collection,
            prefetch=[
                models.Prefetch(
                    query=dense,
                    using="dense",
                    limit=settings.candidate_k,
                    filter=query_filter,
                    params=search_params,
                ),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_indices,
                        values=sparse_values,
                    ),
                    using="sparse",
                    limit=settings.candidate_k,
                    filter=query_filter,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=query_filter,
            limit=settings.candidate_k,
            with_payload=True,
            with_vectors=False,
        )

        chunks: list[Chunk] = []
        for point in result.points:
            payload = point.payload or {}
            text = payload.get("text") or payload.get("page_content") or ""
            if not text:
                continue
            chunks.append(
                Chunk(
                    id=str(payload.get("chunk_id") or point.id),
                    text=text,
                    source=payload.get("source") or payload.get("file_name"),
                    page=payload.get("page_label"),
                    version=payload.get("version"),
                    score=float(point.score),
                    payload=payload,
                )
            )
        return chunks

    def _rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
        if not chunks:
            return []
        pairs = [(query, chunk.text) for chunk in chunks]
        scores = self._reranker.compute_score(pairs, normalize=True)
        if isinstance(scores, (int, float)):
            scores = [scores]
        ranked = sorted(
            zip(scores, chunks),
            key=lambda item: float(item[0]),
            reverse=True,
        )
        result: list[Chunk] = []
        for score, chunk in ranked:
            chunk.score = float(score)
            if chunk.score < settings.rerank_threshold:
                continue
            result.append(chunk)
            if len(result) >= top_k:
                break
        return result

    async def rerank(
        self,
        query: str,
        chunks: list[Chunk],
        top_k: int | None = None,
    ) -> list[Chunk]:
        return await asyncio.to_thread(
            self._rerank,
            query,
            chunks,
            top_k or settings.top_k,
        )

    async def retrieve(
        self,
        query: str,
        tenant_id: str,
        acl: tuple[str, ...],
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[Chunk]:
        candidates = await self.search(query, tenant_id, acl, filters)
        return await self.rerank(query, candidates, top_k)

    async def close(self) -> None:
        await self._client.close()
