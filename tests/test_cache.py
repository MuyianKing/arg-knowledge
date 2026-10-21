from app.core.cache import make_cache_key


def test_cache_key_is_scoped_by_tenant_and_acl() -> None:
    base = dict(
        query="差旅报销标准",
        filters={"doc_type": ["policy"]},
        top_k=5,
        prompt_version="p1",
        model_revision="m1",
    )
    a = make_cache_key(tenant_id="acme", acl=("internal",), **base)
    b = make_cache_key(tenant_id="other", acl=("internal",), **base)
    c = make_cache_key(tenant_id="acme", acl=("confidential",), **base)
    assert a != b
    assert a != c
    assert a == make_cache_key(tenant_id="acme", acl=("internal",), **base)
