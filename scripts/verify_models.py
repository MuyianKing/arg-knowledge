"""Verify that all required model files are present and non-truncated."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"

# path -> minimum bytes
EXPECTED: dict[str, int] = {
    # Embedding: BAAI/bge-m3
    "bge-m3/config.json": 100,
    "bge-m3/pytorch_model.bin": 2_200_000_000,
    "bge-m3/tokenizer.json": 15_000_000,
    "bge-m3/tokenizer_config.json": 100,
    "bge-m3/special_tokens_map.json": 100,
    "bge-m3/sentencepiece.bpe.model": 4_000_000,
    "bge-m3/1_Pooling/config.json": 100,
    "bge-m3/colbert_linear.pt": 1_000_000,
    "bge-m3/sparse_linear.pt": 1_000,
    # Reranker: BAAI/bge-reranker-v2-m3
    "bge-reranker-v2-m3/config.json": 100,
    "bge-reranker-v2-m3/model.safetensors": 2_200_000_000,
    "bge-reranker-v2-m3/tokenizer.json": 15_000_000,
    "bge-reranker-v2-m3/tokenizer_config.json": 100,
    "bge-reranker-v2-m3/special_tokens_map.json": 100,
    "bge-reranker-v2-m3/sentencepiece.bpe.model": 4_000_000,
    # BM25: Qdrant/bm25
    "bm25/config.json": 1,
    "bm25/english.txt": 100,
    "bm25/chinese.txt": 100,
    "bm25/stopwords.txt": 100,
}


def main() -> int:
    missing: list[str] = []
    bad: list[str] = []
    total = 0

    for rel, minimum in EXPECTED.items():
        path = MODELS / rel
        if not path.exists():
            missing.append(rel)
            continue
        size = path.stat().st_size
        total += size
        if size < minimum:
            bad.append(f"{rel}: {size:,} < {minimum:,}")

    print(f"Model root: {MODELS}")
    print(f"Checked {len(EXPECTED)} required files; total {total / 1024**3:.2f} GiB")

    if missing:
        print("\nMISSING:")
        for rel in missing:
            print(f"  - {rel}")
    if bad:
        print("\nTRUNCATED / TOO SMALL:")
        for item in bad:
            print(f"  - {item}")

    if missing or bad:
        return 1

    print("\nAll required model files are present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
