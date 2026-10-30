from __future__ import annotations

import asyncio
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

MASKED_ERROR = 500
DEFAULT_HISTORY = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class IngestJob:
    id: str
    filename: str
    tenant_id: str
    acl: list[str]
    version: str
    doc_type: str
    effective_date: str | None
    status: str = "queued"
    stage: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    documents: int = 0
    chunks: int = 0
    upserted: int = 0
    error: str | None = None
    progress: dict[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobStore:
    """Thread-safe in-memory job history.

    The pipeline runs in a worker thread, so progress updates arrive off the
    event loop. A threading lock keeps the store simple and race-free.
    """

    def __init__(self, limit: int = DEFAULT_HISTORY) -> None:
        self._limit = limit
        self._jobs: dict[str, IngestJob] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def create(self, **kwargs: Any) -> dict[str, Any]:
        job = IngestJob(id=kwargs.pop("id", uuid.uuid4().hex), **kwargs)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._prune()
        return job.to_dict()

    def update(self, job_id: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in fields.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            return job.to_dict()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [self._jobs[job_id] for job_id in reversed(self._order) if job_id in self._jobs]
            return [job.to_dict() for job in jobs[: max(1, min(limit, self._limit))]]

    def _prune(self) -> None:
        while len(self._jobs) > self._limit:
            oldest = self._order.pop(0)
            self._jobs.pop(oldest, None)


async def run_ingest_job(
    app: Any,
    *,
    job_id: str,
    target: Path,
    tenant_id: str,
    acl: tuple[str, ...],
    version: str,
    doc_type: str,
    effective_date: date | None,
) -> None:
    """Run one queued ingestion job and clean up the uploaded file."""

    store: JobStore = app.state.job_store
    pipeline = app.state.ingest
    store.update(job_id, status="running", stage="parsing", started_at=_now())

    def progress(stage: str, current: int, total: int) -> None:
        store.update(
            job_id,
            stage=stage,
            progress={"stage": stage, "current": current, "total": total},
        )

    try:
        if pipeline is None:
            raise RuntimeError("入库流水线未初始化")
        async with app.state.ingest_lock:
            retrieval = app.state.retrieval
            store.update(job_id, stage="loading_models")
            await retrieval.ensure_models()
            store.update(job_id, stage="parsing")
            pipeline.attach_models(retrieval.embedder, retrieval.bm25)
            result = await asyncio.to_thread(
                pipeline.ingest,
                target,
                tenant_id=tenant_id,
                acl=acl,
                version=version,
                effective_date=effective_date,
                doc_type=doc_type,
                progress=progress,
            )
        store.update(
            job_id,
            status="succeeded",
            stage="completed",
            finished_at=_now(),
            documents=int(result.get("documents", 0)),
            chunks=int(result.get("chunks", 0)),
            upserted=int(result.get("upserted", 0)),
            progress=None,
        )
        rag = getattr(app.state, "rag", None)
        if rag is not None:
            await rag.clear_cache()
    except Exception as exc:  # job failures are reported, not raised
        detail = f"{type(exc).__name__}: {exc}"
        store.update(
            job_id,
            status="failed",
            stage="failed",
            finished_at=_now(),
            error=detail[:MASKED_ERROR],
            progress=None,
        )
    finally:
        await asyncio.to_thread(shutil.rmtree, target.parent, ignore_errors=True)
