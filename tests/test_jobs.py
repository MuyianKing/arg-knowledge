from __future__ import annotations

from app.schemas.ingest import JobResponse
from app.services.jobs import JobStore


def _create(store: JobStore, filename: str) -> dict:
    return store.create(
        filename=filename,
        tenant_id="acme",
        acl=["internal"],
        version="v1",
        doc_type="auto",
        effective_date=None,
    )


def test_job_lifecycle_updates_progress() -> None:
    store = JobStore()
    job = _create(store, "policy.md")
    assert job["status"] == "queued"
    assert store.get(job["id"])["stage"] == "queued"

    updated = store.update(
        job["id"],
        status="running",
        stage="embedding",
        progress={"stage": "embedding", "current": 3, "total": 10},
    )
    assert updated is not None
    assert updated["status"] == "running"
    assert updated["progress"] == {"stage": "embedding", "current": 3, "total": 10}

    assert store.update(job["id"], status="succeeded", progress=None)["progress"] is None
    assert store.get("missing") is None


def test_job_store_prunes_oldest_entries() -> None:
    store = JobStore(limit=2)
    ids = [_create(store, f"doc-{index}.md")["id"] for index in range(3)]

    assert store.get(ids[0]) is None
    listed = [job["id"] for job in store.list()]
    assert listed == [ids[2], ids[1]]


def test_progress_dict_satisfies_job_response_schema() -> None:
    store = JobStore()
    job = _create(store, "policy.md")
    store.update(
        job["id"],
        status="running",
        stage="embedding",
        progress={"stage": "embedding", "current": 1, "total": 2},
    )

    parsed = JobResponse(**store.get(job["id"]))
    assert parsed.progress is not None
    assert parsed.progress.stage == "embedding"
    assert parsed.progress.current == 1
    assert parsed.progress.total == 2
