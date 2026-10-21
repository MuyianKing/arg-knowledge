from __future__ import annotations

from pydantic import BaseModel, Field


class Filters(BaseModel):
    doc_type: list[str] | None = None
    version: str | None = None
    is_current: bool | None = True
    effective_date_from: str | None = None


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    filters: Filters | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)
    use_cache: bool = True


class Citation(BaseModel):
    id: str
    score: float
    source: str | None = None
    page: str | None = None
    version: str | None = None
    text: str


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    refused: bool
    top_score: float | None = None
    latency_ms: int
    retrieval_ms: int
    rerank_ms: int
    generation_ms: int
    prompt_version: str
    model_revision: str
    cached: bool = False
    degraded: bool = False
    request_id: str
