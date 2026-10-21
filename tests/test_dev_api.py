import pytest
from fastapi import HTTPException

from app.api.v1.dev import _safe_filename
from app.config import settings
from app.core.llm import LLMClient, mask_api_key

LLM_SETTINGS = [
    "llm_base_url",
    "llm_api_key",
    "llm_model_name",
    "llm_model_revision",
    "llm_temperature",
    "llm_top_p",
    "llm_max_tokens",
    "llm_timeout_seconds",
    "llm_mock",
]


@pytest.fixture
def restore_llm_settings():
    snapshot = {key: getattr(settings, key) for key in LLM_SETTINGS}
    try:
        yield
    finally:
        for key, value in snapshot.items():
            setattr(settings, key, value)


def test_mask_api_key_never_exposes_full_secret() -> None:
    assert mask_api_key("") == ""
    assert mask_api_key("change-me") == ""
    assert mask_api_key("short") == "*****"
    masked = mask_api_key("sk-1234567890abcdef")
    assert masked == "sk-1...cdef"
    assert "567890" not in masked


def test_safe_filename_strips_paths_and_rejects_unknown_types() -> None:
    assert _safe_filename("../../etc/report.md") == "report.md"

    with pytest.raises(HTTPException) as exc:
        _safe_filename("payload.exe")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException):
        _safe_filename(None)


async def test_describe_masks_key(restore_llm_settings) -> None:
    settings.llm_api_key = "sk-abcdefghijklmnop"
    client = LLMClient()
    try:
        described = client.describe()
    finally:
        await client.close()

    assert described["api_key_set"] is True
    assert described["api_key_masked"] == "sk-a...mnop"


async def test_reconfigure_applies_runtime_settings(restore_llm_settings) -> None:
    client = LLMClient()
    try:
        described = await client.reconfigure(
            base_url="https://api.example.com/v1/",
            api_key="sk-1234567890abcdef",
            model_name="demo-model",
            model_revision="demo-model@2026-10",
            temperature=0.3,
            top_p=0.8,
            max_tokens=256,
            timeout_seconds=20,
            mock=True,
        )
    finally:
        await client.close()

    assert described["base_url"] == "https://api.example.com/v1"
    assert described["model_name"] == "demo-model"
    assert described["model_revision"] == "demo-model@2026-10"
    assert described["mock"] is True
    assert described["temperature"] == 0.3
    assert described["top_p"] == 0.8
    assert described["max_tokens"] == 256
    assert described["timeout_seconds"] == 20
    assert described["api_key_masked"] == "sk-1...cdef"
    assert settings.llm_base_url == "https://api.example.com/v1"


async def test_connection_without_key_reports_not_configured(restore_llm_settings) -> None:
    settings.llm_api_key = "change-me"
    client = LLMClient()
    try:
        result = await client.test_connection()
    finally:
        await client.close()

    assert result["ok"] is False
    assert "未配置" in result["error"]
    assert result["latency_ms"] == 0
