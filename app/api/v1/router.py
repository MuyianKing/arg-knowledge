from fastapi import APIRouter

from app.api.v1.ask import router as ask_router
from app.config import settings

router = APIRouter()
router.include_router(ask_router)

if settings.dev_tools_enabled:
    from app.api.v1.dev import router as dev_router

    router.include_router(dev_router)
