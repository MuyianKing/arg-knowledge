from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.routes import router
from app.api.v1.router import router as v1_router
from app.config import settings
from app.core.cache import Cache, MemoryCache
from app.core.llm import LLMClient
from app.core.retrieval import RetrievalService
from app.services.jobs import JobStore
from app.services.rag import RAGService


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis = (
        Redis.from_url(settings.redis_url, decode_responses=True)
        if settings.cache_enabled
        else None
    )
    retrieval = RetrievalService()
    llm = LLMClient()
    app.state.retrieval = retrieval
    app.state.llm = llm
    app.state.rag = RAGService(
        retrieval,
        llm,
        Cache(redis) if redis is not None else MemoryCache(),
    )
    app.state.ingest = None
    app.state.ingest_lock = None
    app.state.ingest_tasks = set()
    app.state.job_store = JobStore()
    app.state.warmup_ms = None
    if settings.warmup_on_startup:
        started = time.monotonic()
        await retrieval.ensure_models()
        app.state.warmup_ms = int((time.monotonic() - started) * 1000)

    from app.ingest.pipeline import IngestPipeline

    app.state.ingest = IngestPipeline()
    app.state.ingest_lock = asyncio.Lock()
    try:
        yield
    finally:
        if app.state.ingest is not None:
            await asyncio.to_thread(app.state.ingest.close)
        await retrieval.close()
        await llm.close()
        if redis is not None:
            await redis.aclose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(router)
app.include_router(v1_router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "docs": "/docs"}
