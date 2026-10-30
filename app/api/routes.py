from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Request

from app.config import settings

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    models = {
        "bge_m3": Path(settings.bge_m3_path).exists(),
        "bge_reranker": Path(settings.bge_reranker_path).exists(),
        "bm25": Path(settings.bm25_model_path).exists(),
    }
    qdrant_ok = True
    try:
        await request.app.state.retrieval.client.get_collections()
    except Exception:
        qdrant_ok = False

    status = "ok" if all(models.values()) and qdrant_ok else "degraded"
    retrieval = request.app.state.retrieval
    return {
        "status": status,
        "ts": int(time.time()),
        "ready": retrieval.is_loaded,
        "warmup_ms": getattr(request.app.state, "warmup_ms", None),
        "warmup_on_startup": settings.warmup_on_startup,
        "models": models,
        "qdrant": qdrant_ok,
    }
