from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.ingest.parsers import SUPPORTED_EXTENSIONS

_UPLOAD_CHUNK = 1024 * 1024


def safe_filename(filename: str | None) -> str:
    """Strip directories and reject unsupported upload extensions."""

    raw = (filename or "").replace("\\", "/")
    name = Path(raw).name.strip()
    if not name or name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少文件名",
        )
    if len(name) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名过长",
        )
    if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型，允许：{allowed}",
        )
    return name


async def save_upload(file: UploadFile, target: Path, max_bytes: int) -> int:
    """Stream an upload to disk and enforce a hard size limit."""

    size = 0
    handle = await asyncio.to_thread(target.open, "wb")
    try:
        while chunk := await file.read(_UPLOAD_CHUNK):
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"文件超过 {max_bytes // (1024 * 1024)} MB 限制",
                )
            await asyncio.to_thread(handle.write, chunk)
    finally:
        await asyncio.to_thread(handle.close)
        await file.close()
    return size
