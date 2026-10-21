"""Create the Qdrant collection with dense + sparse vectors and payload indexes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client import QdrantClient, models

from app.config import settings

PAYLOAD_INDEXES: dict[str, models.PayloadSchemaType] = {
    "doc_id": models.PayloadSchemaType.KEYWORD,
    "chunk_id": models.PayloadSchemaType.KEYWORD,
    "tenant_id": models.PayloadSchemaType.KEYWORD,
    "acl": models.PayloadSchemaType.KEYWORD,
    "doc_type": models.PayloadSchemaType.KEYWORD,
    "version": models.PayloadSchemaType.KEYWORD,
    "is_current": models.PayloadSchemaType.BOOL,
    "source": models.PayloadSchemaType.KEYWORD,
    "content_hash": models.PayloadSchemaType.KEYWORD,
    "effective_date": models.PayloadSchemaType.DATETIME,
    "chunk_index": models.PayloadSchemaType.INTEGER,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--shard-number", type=int, default=None)
    parser.add_argument("--replication-factor", type=int, default=None)
    args = parser.parse_args()

    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=30,
    )

    if client.collection_exists(settings.qdrant_collection):
        if not args.recreate:
            print(f"Collection {settings.qdrant_collection!r} already exists.")
            print("Use --recreate to delete and rebuild it.")
            return
        print(f"Deleting existing collection {settings.qdrant_collection!r}...")
        client.delete_collection(settings.qdrant_collection)

    print(f"Creating collection {settings.qdrant_collection!r}...")
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config={
            "dense": models.VectorParams(
                size=1024,
                distance=models.Distance.COSINE,
                memory=models.Memory.COLD,
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        quantile=0.99,
                        memory=models.Memory.PINNED,
                    )
                ),
            )
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(
                index=models.SparseIndexParams(memory=models.Memory.PINNED),
                modifier=models.Modifier.IDF,
            )
        },
        payload=models.PayloadStorageParams(memory=models.Memory.COLD),
        shard_number=args.shard_number,
        replication_factor=args.replication_factor,
    )

    for field_name, field_schema in PAYLOAD_INDEXES.items():
        print(f"  payload index: {field_name}")
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name=field_name,
            field_schema=field_schema,
        )

    info = client.get_collection(settings.qdrant_collection)
    print(info)
    print("Done.")


if __name__ == "__main__":
    main()
