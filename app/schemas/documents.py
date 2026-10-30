from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentItem(BaseModel):
    doc_id: str
    source: str | None = None
    version: str | None = None
    doc_type: str | None = None
    effective_date: str | None = None
    is_current: bool = True
    acl: list[str] = Field(default_factory=list)
    chunks: int = 0


class DocumentListResponse(BaseModel):
    items: list[DocumentItem] = Field(default_factory=list)
    scanned_chunks: int = 0
    truncated: bool = False


class DeleteDocumentResponse(BaseModel):
    doc_id: str
    deleted_chunks: int
