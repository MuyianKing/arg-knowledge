"""Call the local engine /api/v1/ask endpoint for a quick manual check."""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--tenant", default="acme")
    parser.add_argument("--acl", default="internal")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{args.base_url.rstrip('/')}/api/v1/ask",
            headers={
                "X-Tenant-Id": args.tenant,
                "X-Acl": args.acl,
            },
            json={"query": args.query, "top_k": args.top_k},
        )
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
