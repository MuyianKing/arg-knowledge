#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"
export HF_ENDPOINT
export HF_HUB_DISABLE_TELEMETRY=1

HF=".venv/Scripts/hf.exe"
if [[ ! -x "$HF" ]]; then
  echo "ERROR: hf CLI not found at $HF"
  echo "Run: uv venv --python 3.12 .venv && uv pip install --python .venv/Scripts/python.exe huggingface_hub hf_xet"
  exit 1
fi

mkdir -p models

# Pinned revisions (see models/README.md)
BGE_M3_REV="5617a9f61b028005a4858fdac845db406aefb181"
RERANKER_REV="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
BM25_REV="22b8d2af71a76161e18dd432d2cee0eefa66e412"

echo "==> [1/3] BAAI/bge-m3"
"$HF" download BAAI/bge-m3 \
  --revision "$BGE_M3_REV" \
  --local-dir models/bge-m3 \
  --max-workers 8 \
  --exclude "onnx/*" \
  --exclude "imgs/*" \
  --exclude "*.jpg" \
  --exclude "*.webp" \
  --exclude "*.DS_Store"

echo "==> [2/3] BAAI/bge-reranker-v2-m3"
"$HF" download BAAI/bge-reranker-v2-m3 \
  --revision "$RERANKER_REV" \
  --local-dir models/bge-reranker-v2-m3 \
  --max-workers 8 \
  --exclude "assets/*"

echo "==> [3/3] Qdrant/bm25"
"$HF" download Qdrant/bm25 \
  --revision "$BM25_REV" \
  --local-dir models/bm25 \
  --max-workers 8

echo "==> Download complete. Verifying..."
.venv/Scripts/python.exe scripts/verify_models.py
