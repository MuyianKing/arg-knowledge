"""Ingest a file or directory into Qdrant."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingest.pipeline import IngestPipeline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--acl", default="internal", help="comma-separated ACL labels")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--effective-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--doc-type", default="auto")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    effective = date.fromisoformat(args.effective_date) if args.effective_date else None
    pipeline = IngestPipeline()
    try:
        result = pipeline.ingest(
            args.path,
            tenant_id=args.tenant,
            acl=[part.strip() for part in args.acl.split(",") if part.strip()],
            version=args.version,
            effective_date=effective,
            doc_type=args.doc_type,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
    finally:
        pipeline.close()

    print(result)


if __name__ == "__main__":
    main()
