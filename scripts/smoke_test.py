"""Smoke-test local models and backing services.

Examples:
    python scripts/smoke_test.py --skip-services
    python scripts/smoke_test.py --skip-models
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import redis
from qdrant_client import QdrantClient

from app.config import settings


def check_models() -> None:
    from fastembed.sparse.bm25 import Bm25
    from FlagEmbedding import BGEM3FlagModel, FlagReranker

    print("[models] loading BGE-M3...")
    embedder = BGEM3FlagModel(str(settings.bge_m3_path), use_fp16=True)
    out = embedder.encode(
        ["差旅报销标准是多少"],
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
        max_length=512,
    )
    print(f"[models] dense dim = {len(out['dense_vecs'][0])}")

    print("[models] loading reranker...")
    reranker = FlagReranker(str(settings.bge_reranker_path), use_fp16=True)
    scores = reranker.compute_score(
        [
            ("差旅报销标准是多少", "市内交通费每日上限 80 元。"),
            ("差旅报销标准是多少", "今天天气很好。"),
        ],
        normalize=True,
    )
    print(f"[models] rerank scores = {scores}")

    print("[models] loading BM25...")
    bm25 = Bm25(
        model_name="Qdrant/bm25",
        specific_model_path=str(settings.bm25_model_path),
        disable_stemmer=True,
    )
    import jieba

    sparse = next(iter(bm25.embed([" ".join(jieba.cut("差旅报销标准是多少"))])))
    print(f"[models] sparse nnz = {len(sparse.indices)}")


def check_services() -> None:
    print("[services] Qdrant...")
    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=10,
    )
    try:
        collections = client.get_collections().collections
        print(f"[services] collections = {[c.name for c in collections]}")
    finally:
        client.close()

    print("[services] Redis...")
    r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        print(f"[services] redis ping = {r.ping()}")
    finally:
        r.close()

    print("[services] LLM API...")
    try:
        response = httpx.get(
            f"{settings.llm_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        print(f"[services] LLM models = {response.json()}")
    except Exception as exc:
        print(f"[services] LLM API unavailable: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument("--skip-services", action="store_true")
    args = parser.parse_args()

    missing = [
        name
        for name, path in {
            "bge-m3": settings.bge_m3_path,
            "bge-reranker-v2-m3": settings.bge_reranker_path,
            "bm25": settings.bm25_model_path,
        }.items()
        if not Path(path).exists()
    ]
    if missing:
        print(f"WARNING: missing model directories: {missing}")

    if not args.skip_models:
        check_models()
    if not args.skip_services:
        check_services()


if __name__ == "__main__":
    main()
