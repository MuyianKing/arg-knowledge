from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.documents import group_documents


def _point(**payload) -> SimpleNamespace:
    return SimpleNamespace(payload=payload)


def test_group_documents_merges_chunks_and_acl() -> None:
    points = [
        _point(
            doc_id="doc-a",
            source="policy.md",
            version="v1",
            doc_type="policy",
            effective_date="2025-01-01T00:00:00",
            is_current=True,
            acl=["internal"],
        ),
        _point(
            doc_id="doc-a",
            source="policy.md",
            version="v1",
            doc_type="policy",
            effective_date="2025-01-01T00:00:00",
            is_current=True,
            acl=["finance"],
        ),
        _point(doc_id="doc-b", source="handbook.md", version="v2", acl="internal"),
        _point(source="no-doc-id.md"),
    ]

    documents = group_documents(points)

    assert [item.doc_id for item in documents] == ["doc-b", "doc-a"]
    policy = next(item for item in documents if item.doc_id == "doc-a")
    assert policy.chunks == 2
    assert policy.acl == ["finance", "internal"]
    assert policy.source == "policy.md"
    assert policy.version == "v1"

    handbook = documents[0]
    assert handbook.chunks == 1
    assert handbook.acl == ["internal"]
    assert handbook.effective_date is None


def test_group_documents_returns_empty_for_unknown_payloads() -> None:
    assert group_documents([_point(text="chunk without doc id")]) == []
