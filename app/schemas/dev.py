from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.api.schemas import Filters


class LLMConfigUpdate(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=200)
    model_revision: str | None = Field(default=None, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    mock: bool | None = None

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return value


class LLMConfigResponse(BaseModel):
    base_url: str
    model_name: str
    model_revision: str
    api_key_set: bool
    api_key_masked: str
    mock: bool
    temperature: float
    top_p: float
    max_tokens: int
    timeout_seconds: float
    circuit_open: bool


class LLMTestResponse(BaseModel):
    ok: bool
    model: str
    latency_ms: int
    error: str | None = None
    reply: str | None = None
    finish_reason: str | None = None


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    filters: Filters | None = None


class RetrievedChunk(BaseModel):
    id: str
    score: float
    source: str | None = None
    page: str | None = None
    version: str | None = None
    text: str


class RetrieveResponse(BaseModel):
    chunks: list[RetrievedChunk]
    candidates: int
    retrieval_ms: int
    rerank_ms: int
    latency_ms: int


class IngestResponse(BaseModel):
    filename: str
    tenant_id: str
    acl: list[str]
    version: str
    doc_type: str
    dry_run: bool
    documents: int
    chunks: int
    upserted: int
    elapsed_ms: int
