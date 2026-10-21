from app.core.retrieval import _as_list, build_filter


def test_as_list() -> None:
    assert _as_list(None) == []
    assert _as_list("policy") == ["policy"]
    assert _as_list(["policy", "sop"]) == ["policy", "sop"]


def test_build_filter_has_tenant_current_and_acl() -> None:
    qfilter = build_filter(
        "acme",
        ("internal",),
        {"doc_type": ["policy"], "version": "v2.1"},
    )
    assert qfilter.must is not None
    keys = [condition.key for condition in qfilter.must]
    assert "tenant_id" in keys
    assert "is_current" in keys
    assert "doc_type" in keys
    assert "version" in keys
    assert qfilter.should is not None
    assert qfilter.should[0].key == "acl"
