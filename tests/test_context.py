import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.context import get_engine_context


def _request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in headers.items()
        ],
    }
    return Request(scope)


async def test_missing_tenant_returns_400() -> None:
    with pytest.raises(HTTPException) as exc:
        await get_engine_context(_request({"X-Acl": "internal"}))
    assert exc.value.status_code == 400


async def test_missing_acl_returns_400() -> None:
    with pytest.raises(HTTPException) as exc:
        await get_engine_context(_request({"X-Tenant-Id": "acme"}))
    assert exc.value.status_code == 400


async def test_valid_context_parses_acl() -> None:
    context = await get_engine_context(
        _request({"X-Tenant-Id": "acme", "X-Acl": "internal,finance"})
    )
    assert context.tenant_id == "acme"
    assert context.acl == ("internal", "finance")
