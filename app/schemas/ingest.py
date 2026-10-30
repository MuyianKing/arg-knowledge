from __future__ import annotations

from pydantic import BaseModel, Field


class IngestAccepted(BaseModel):
    job_id: str
    status: str = "queued"


class JobProgress(BaseModel):
    stage: str
    current: int = 0
    total: int = 0


class JobResponse(BaseModel):
    id: str
    status: str
    stage: str
    filename: str
    tenant_id: str
    acl: list[str]
    version: str
    doc_type: str
    effective_date: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    documents: int = 0
    chunks: int = 0
    upserted: int = 0
    error: str | None = None
    progress: JobProgress | None = None


class JobListResponse(BaseModel):
    items: list[JobResponse] = Field(default_factory=list)
