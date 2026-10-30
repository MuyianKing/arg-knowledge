"""Verify that all required model files are present and non-truncated.

The desktop setup wizard runs this with ``--json`` to drive the model step.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_REPO_RUNTIME = ROOT / "runtime" / "models"
if not os.environ.get("APP_HOME") and _REPO_RUNTIME.is_dir():
    DEFAULT_MODELS = _REPO_RUNTIME
else:
    DEFAULT_MODELS = Path(os.environ.get("APP_HOME") or ROOT) / "models"

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


def inspect(models_dir: Path) -> dict:
    missing: list[str] = []
    truncated: list[dict] = []
    total = 0

    for rel, minimum in EXPECTED.items():
        path = models_dir / rel
        if not path.exists():
            missing.append(rel)
            continue
        size = path.stat().st_size
        total += size
        if size < minimum:
            truncated.append({"path": rel, "size": size, "minimum": minimum})

    return {
        "ok": not missing and not truncated,
        "model_root": str(models_dir),
        "checked": len(EXPECTED),
        "total_bytes": total,
        "missing": missing,
        "truncated": truncated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify required model files")
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS,
        help=f"model root (default: {DEFAULT_MODELS})",
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable report")
    args = parser.parse_args()

    report = inspect(args.models_dir)

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"Model root: {report['model_root']}")
        print(
            f"Checked {report['checked']} required files; "
            f"total {report['total_bytes'] / 1024**3:.2f} GiB"
        )
        if report["missing"]:
            print("\nMISSING:")
            for rel in report["missing"]:
                print(f"  - {rel}")
        if report["truncated"]:
            print("\nTRUNCATED / TOO SMALL:")
            for item in report["truncated"]:
                print(f"  - {item['path']}: {item['size']:,} < {item['minimum']:,}")
        if report["ok"]:
            print("\nAll required model files are present.")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
