"""Download the pinned local models used by the engine.

The desktop setup wizard runs this with the deployment venv's Python and reads
the JSON lines from stdout. It is also usable from a terminal:

    .venv/Scripts/python.exe scripts/download_models.py
    .venv/Scripts/python.exe scripts/download_models.py \
        --mirror https://hf-mirror.com
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS_DIR = ROOT / "runtime" / "models"

# repo_id -> (revision, ignore patterns, local subdirectory)
REPOS: dict[str, tuple[str, list[str], str]] = {
    "BAAI/bge-m3": (
        "5617a9f61b028005a4858fdac845db406aefb181",
        ["onnx/*", "imgs/*", "*.jpg", "*.webp", "*.DS_Store"],
        "bge-m3",
    ),
    "BAAI/bge-reranker-v2-m3": (
        "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
        ["assets/*"],
        "bge-reranker-v2-m3",
    ),
    "Qdrant/bm25": (
        "22b8d2af71a76161e18dd432d2cee0eefa66e412",
        [],
        "bm25",
    ),
}


def emit(event: str, **payload: object) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download pinned RAG models")
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument(
        "--mirror",
        default=None,
        help="HuggingFace endpoint, e.g. https://hf-mirror.com",
    )
    parser.add_argument(
        "--repo",
        action="append",
        default=None,
        help="only download the given repo id (repeatable)",
    )
    args = parser.parse_args()

    if args.mirror:
        os.environ["HF_ENDPOINT"] = args.mirror.strip()
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    args.models_dir.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # pragma: no cover - dependency error path
        emit("error", message=f"无法导入 huggingface_hub: {exc}")
        return 2

    selected = set(args.repo or REPOS)
    total = len([repo for repo in REPOS if repo in selected])
    index = 0
    for repo_id, (revision, ignores, folder) in REPOS.items():
        if repo_id not in selected:
            continue
        index += 1
        target = args.models_dir / folder
        emit(
            "stage",
            repo=repo_id,
            index=index,
            total=total,
            message=f"[{index}/{total}] 下载 {repo_id} -> {target}",
        )
        try:
            snapshot_download(
                repo_id=repo_id,
                revision=revision,
                local_dir=str(target),
                max_workers=8,
                ignore_patterns=ignores,
            )
        except Exception as exc:  # pragma: no cover - network path
            emit("error", repo=repo_id, message=f"{repo_id} 下载失败: {exc}")
            return 1
        emit("done", repo=repo_id, message=f"[{index}/{total}] {repo_id} 完成")

    emit("completed", message="全部模型下载完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
