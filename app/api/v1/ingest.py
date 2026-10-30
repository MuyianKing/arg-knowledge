from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import date
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from app.config import settings
from app.core.context import EngineContext, get_engine_context
from app.core.uploads import safe_filename, save_upload
from app.schemas.ingest import IngestAccepted, JobListResponse, JobResponse
from app.services.jobs import run_ingest_job

router = APIRouter(tags=["ingest"])


@router.post(
    "/ingest",
    response_model=IngestAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="提交异步入库任务",
)
async def submit_ingest(
    request: Request,
    file: UploadFile = File(...),
    version: str = Form("v1", max_length=100),
    doc_type: str = Form("auto", max_length=100),
    effective_date: str | None = Form(None, max_length=20),
    context: EngineContext = Depends(get_engine_context),
) -> IngestAccepted:
    name = safe_filename(file.filename)
    try:
        effective = date.fromisoformat(effective_date) if effective_date else None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="effective_date 必须是 YYYY-MM-DD",
        ) from exc

    target_dir = Path(settings.upload_dir) / uuid.uuid4().hex
    await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
    target = target_dir / name

    try:
        await save_upload(file, target, settings.max_upload_mb * 1024 * 1024)
    except HTTPException:
        await asyncio.to_thread(shutil.rmtree, target_dir, ignore_errors=True)
        raise
    except Exception as exc:
        await asyncio.to_thread(shutil.rmtree, target_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存上传文件失败：{type(exc).__name__}: {exc}"[:500],
        ) from exc

    job = request.app.state.job_store.create(
        filename=name,
        tenant_id=context.tenant_id,
        acl=list(context.acl),
        version=version,
        doc_type=doc_type,
        effective_date=effective_date,
    )

    task = asyncio.create_task(
        run_ingest_job(
            request.app,
            job_id=job["id"],
            target=target,
            tenant_id=context.tenant_id,
            acl=context.acl,
            version=version,
            doc_type=doc_type,
            effective_date=effective,
        )
    )
    request.app.state.ingest_tasks.add(task)
    task.add_done_callback(request.app.state.ingest_tasks.discard)

    return IngestAccepted(job_id=job["id"], status=job["status"])


@router.get("/jobs", response_model=JobListResponse, summary="最近入库任务")
async def list_jobs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    context: EngineContext = Depends(get_engine_context),
) -> JobListResponse:
    store = request.app.state.job_store
    items = [job for job in store.list(limit=limit * 3) if job["tenant_id"] == context.tenant_id][
        :limit
    ]
    return JobListResponse(items=[JobResponse(**job) for job in items])


@router.get("/jobs/{job_id}", response_model=JobResponse, summary="查询入库任务状态")
async def get_job(
    request: Request,
    job_id: str,
    context: EngineContext = Depends(get_engine_context),
) -> JobResponse:
    job = request.app.state.job_store.get(job_id)
    if job is None or job["tenant_id"] != context.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )
    return JobResponse(**job)
