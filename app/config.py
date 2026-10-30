from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

# Resolved from the process environment only, before .env is loaded.
# The desktop shell sets APP_HOME to %LOCALAPPDATA%/ARG-Knowledge so the
# engine, models and uploads live outside the (read-only) install directory.
# CLI usage keeps the repository root as the default.
APP_HOME = Path(os.environ.get("APP_HOME") or ROOT).expanduser().resolve()

# Repository development keeps large runtime data under runtime/ so the source
# tree stays small. A deployed engine sets APP_HOME and uses APP_HOME/models.
_RUNTIME = ROOT / "runtime"
_USE_REPO_RUNTIME = not os.environ.get("APP_HOME") and _RUNTIME.is_dir()
MODELS_ROOT = _RUNTIME / "models" if _USE_REPO_RUNTIME else APP_HOME / "models"
DATA_ROOT = _RUNTIME / "data" if _USE_REPO_RUNTIME else APP_HOME / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=APP_HOME / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "enterprise-rag"
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: str = ""
    # Local debugging endpoints under /api/v1/dev. Never enable in production.
    dev_tools_enabled: bool = False

    # Local model directories (see models/README.md)
    bge_m3_path: Path = MODELS_ROOT / "bge-m3"
    bge_reranker_path: Path = MODELS_ROOT / "bge-reranker-v2-m3"
    bm25_model_path: Path = MODELS_ROOT / "bm25"

    # Qdrant
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "kb"

    # Redis
    redis_url: str = "redis://127.0.0.1:6379/0"
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600

    # LLM: external OpenAI-compatible API
    llm_base_url: str = "https://api.example.com/v1"
    llm_api_key: str = "change-me"
    llm_model_name: str = "your-model"
    llm_temperature: float = 0.1
    llm_top_p: float = 0.9
    llm_max_tokens: int = 512
    llm_timeout_seconds: float = 10.0
    llm_max_model_len: int = 8192
    llm_model_revision: str = "your-model@2026-xx"
    llm_mock: bool = False
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 0.5
    llm_circuit_breaker_threshold: int = 5
    llm_circuit_breaker_cooldown_seconds: float = 30.0
    llm_redact_pii: bool = False
    llm_extra_headers: dict[str, str] = Field(default_factory=dict)
    prompt_version: str = "p1"

    # Retrieval
    top_k: int = 5
    candidate_k: int = 50
    rrf_k: int = 60
    rerank_threshold: float = 0.0
    embedding_max_length: int = 512
    # Load BGE-M3/reranker during startup. The desktop shell enables this so
    # /health only reports ready after the first query is warm.
    warmup_on_startup: bool = False

    # Ingestion
    chunk_size: int = 512
    chunk_overlap: int = 50
    ingest_batch_size: int = 64
    upload_dir: Path = DATA_ROOT / "uploads"
    max_upload_mb: int = 100


settings = Settings()
