from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

TENANT_HEADER = "X-Tenant-Id"
ACL_HEADER = "X-Acl"


@dataclass(frozen=True)
class EngineContext:
    """Trusted caller context injected by the gateway."""

    tenant_id: str
    acl: tuple[str, ...]


def _parse_acl(raw: str) -> tuple[str, ...]:
    value = raw.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"missing {ACL_HEADER}",
        )

    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{ACL_HEADER} must be a comma-separated string or JSON array",
            ) from exc
        if not isinstance(parsed, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{ACL_HEADER} must be a JSON array",
            )
        acl = tuple(str(item).strip() for item in parsed if str(item).strip())
    else:
        acl = tuple(part.strip() for part in value.split(",") if part.strip())

    if not acl:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{ACL_HEADER} must not be empty",
        )
    return acl


async def get_engine_context(request: Request) -> EngineContext:
    """Read the trusted tenant/ACL headers injected by the gateway.

    The engine does not authenticate users or API keys. It only accepts
    traffic from the internal gateway and enforces these values as data
    isolation filters.
    """

    tenant_id = (request.headers.get(TENANT_HEADER) or "").strip()
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"missing {TENANT_HEADER}",
        )

    acl_raw = request.headers.get(ACL_HEADER) or ""
    return EngineContext(tenant_id=tenant_id, acl=_parse_acl(acl_raw))
