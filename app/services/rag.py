from __future__ import annotations

import time
from typing import Any

from app.api.schemas import AskRequest, AskResponse, Citation
from app.config import settings
from app.core.cache import CacheProtocol, make_cache_key
from app.core.context import EngineContext
from app.core.llm import (
    NO_ANSWER,
    LLMClient,
    LLMUnavailable,
    sanitize_citations,
    truncate_chunks,
)
from app.core.retrieval import RetrievalService

REFUSAL_ANSWER = "根据现有资料无法回答该问题。"


class RAGService:
    def __init__(
        self,
        retrieval: RetrievalService,
        llm: LLMClient,
        cache: CacheProtocol,
    ) -> None:
        self._retrieval = retrieval
        self._llm = llm
        self._cache = cache

    async def clear_cache(self) -> None:
        """Invalidate cached answers after documents are ingested or deleted."""

        await self._cache.clear()

    async def answer(
        self,
        request: AskRequest,
        context: EngineContext,
        request_id: str,
    ) -> AskResponse:
        started = time.perf_counter()
        filters = request.filters.model_dump(exclude_none=True) if request.filters else {}
        top_k = request.top_k or settings.top_k

        cache_key = make_cache_key(
            tenant_id=context.tenant_id,
            acl=context.acl,
            query=request.query,
            filters=filters,
            top_k=top_k,
            prompt_version=settings.prompt_version,
            model_revision=settings.llm_model_revision,
        )

        if request.use_cache:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                return AskResponse(
                    **cached,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    retrieval_ms=0,
                    rerank_ms=0,
                    generation_ms=0,
                    cached=True,
                    request_id=request_id,
                )

        retrieval_started = time.perf_counter()
        candidates = await self._retrieval.search(
            request.query,
            context.tenant_id,
            context.acl,
            filters,
        )
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

        rerank_started = time.perf_counter()
        chunks = await self._retrieval.rerank(request.query, candidates, top_k)
        rerank_ms = int((time.perf_counter() - rerank_started) * 1000)

        if not chunks:
            return self._refusal(
                started=started,
                retrieval_ms=retrieval_ms,
                rerank_ms=rerank_ms,
                generation_ms=0,
                top_score=None,
                request_id=request_id,
            )

        top_score = max(chunk.score for chunk in chunks)
        if top_score < settings.rerank_threshold:
            return self._refusal(
                started=started,
                retrieval_ms=retrieval_ms,
                rerank_ms=rerank_ms,
                generation_ms=0,
                top_score=top_score,
                request_id=request_id,
            )

        context_chunks = [
            {
                "id": f"S{index}",
                "text": chunk.text,
                "source": chunk.source,
                "page": chunk.page,
                "version": chunk.version,
                "score": chunk.score,
            }
            for index, chunk in enumerate(chunks, start=1)
        ]
        context_chunks = truncate_chunks(request.query, context_chunks)
        if not context_chunks:
            return self._refusal(
                started=started,
                retrieval_ms=retrieval_ms,
                rerank_ms=rerank_ms,
                generation_ms=0,
                top_score=top_score,
                request_id=request_id,
            )

        generation_started = time.perf_counter()
        try:
            llm_result = await self._llm.generate(request.query, context_chunks)
        except LLMUnavailable:
            return self._degraded(
                started=started,
                retrieval_ms=retrieval_ms,
                rerank_ms=rerank_ms,
                generation_ms=int((time.perf_counter() - generation_started) * 1000),
                top_score=top_score,
                context_chunks=context_chunks,
                request_id=request_id,
            )
        generation_ms = int((time.perf_counter() - generation_started) * 1000)

        if not llm_result.answer or NO_ANSWER in llm_result.answer.upper():
            return self._refusal(
                started=started,
                retrieval_ms=retrieval_ms,
                rerank_ms=rerank_ms,
                generation_ms=generation_ms,
                top_score=top_score,
                request_id=request_id,
            )

        valid_ids = {chunk["id"] for chunk in context_chunks}
        cleaned_answer, used_ids = sanitize_citations(llm_result.answer, valid_ids)
        citation_by_id = {chunk["id"]: chunk for chunk in context_chunks}
        citations = [
            Citation(
                id=citation_id,
                score=citation_by_id[citation_id]["score"],
                source=citation_by_id[citation_id]["source"],
                page=citation_by_id[citation_id]["page"],
                version=citation_by_id[citation_id]["version"],
                text=citation_by_id[citation_id]["text"],
            )
            for citation_id in sorted(used_ids, key=lambda item: int(item[1:]))
        ]

        payload: dict[str, Any] = {
            "answer": cleaned_answer,
            "citations": [citation.model_dump() for citation in citations],
            "refused": False,
            "top_score": top_score,
            "prompt_version": settings.prompt_version,
            "model_revision": settings.llm_model_revision,
        }
        if request.use_cache:
            await self._cache.set(cache_key, payload)

        return AskResponse(
            **payload,
            latency_ms=int((time.perf_counter() - started) * 1000),
            retrieval_ms=retrieval_ms,
            rerank_ms=rerank_ms,
            generation_ms=generation_ms,
            cached=False,
            request_id=request_id,
        )

    def _degraded(
        self,
        *,
        started: float,
        retrieval_ms: int,
        rerank_ms: int,
        generation_ms: int,
        top_score: float | None,
        context_chunks: list[dict[str, Any]],
        request_id: str,
    ) -> AskResponse:
        citations = [
            Citation(
                id=chunk["id"],
                score=chunk["score"],
                source=chunk["source"],
                page=chunk["page"],
                version=chunk["version"],
                text=chunk["text"],
            )
            for chunk in context_chunks
        ]
        return AskResponse(
            answer="LLM 服务暂时不可用，以下为检索到的相关片段，未生成答案。",
            citations=citations,
            refused=False,
            degraded=True,
            top_score=top_score,
            latency_ms=int((time.perf_counter() - started) * 1000),
            retrieval_ms=retrieval_ms,
            rerank_ms=rerank_ms,
            generation_ms=generation_ms,
            prompt_version=settings.prompt_version,
            model_revision=settings.llm_model_revision,
            cached=False,
            request_id=request_id,
        )

    def _refusal(
        self,
        *,
        started: float,
        retrieval_ms: int,
        rerank_ms: int,
        generation_ms: int,
        top_score: float | None,
        request_id: str,
    ) -> AskResponse:
        return AskResponse(
            answer=REFUSAL_ANSWER,
            citations=[],
            refused=True,
            top_score=top_score,
            latency_ms=int((time.perf_counter() - started) * 1000),
            retrieval_ms=retrieval_ms,
            rerank_ms=rerank_ms,
            generation_ms=generation_ms,
            prompt_version=settings.prompt_version,
            model_revision=settings.llm_model_revision,
            cached=False,
            request_id=request_id,
        )
