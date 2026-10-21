from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from app.api.schemas import AskRequest, AskResponse
from app.core.context import EngineContext, get_engine_context

router = APIRouter(tags=["ask"])


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="知识库问答",
)
async def ask(
    body: AskRequest,
    request: Request,
    context: EngineContext = Depends(get_engine_context),
) -> AskResponse:
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
    return await request.app.state.rag.answer(body, context, request_id)
