from pathlib import Path

from app.ingest.pipeline import IngestPipeline


def test_dry_run_counts_chunks(tmp_path: Path) -> None:
    doc = tmp_path / "policy.txt"
    doc.write_text(
        "差旅报销制度。市内交通费每日上限 80 元。住宿费按城市分级。",
        encoding="utf-8",
    )
    pipeline = IngestPipeline()
    try:
        result = pipeline.ingest(
            tmp_path,
            tenant_id="acme",
            acl=["internal"],
            version="v1",
            dry_run=True,
        )
    finally:
        pipeline.close()

    assert result["documents"] >= 1
    assert result["chunks"] >= 1
    assert result["upserted"] == 0
