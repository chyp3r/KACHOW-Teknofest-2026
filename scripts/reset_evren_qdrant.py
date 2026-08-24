"""Delete every collection on Evren's remote Qdrant cluster (EVREN_QDRANT_URL).

Team-isolated (see /mimari on the Evren docs site), so this only ever
touches this team's own data -- but it is still irreversible, hits a real
remote service, and is not scoped to one collection the way
`make reset-document-qa` is against the local Qdrant. Confirmation is
enforced by the Makefile target (`make reset-evren-qdrant CONFIRM=yes`), not
here, to keep this script itself non-interactive and scriptable like every
other one in this directory.

Usage:
    docker compose run --rm --no-deps backend python scripts/reset_evren_qdrant.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings  # noqa: E402
from qdrant_client import AsyncQdrantClient  # noqa: E402


async def main() -> int:
    if not settings.EVREN_QDRANT_URL:
        print(
            "EVREN_QDRANT_URL is not set -- nothing to reset. "
            "Set it (and EVREN_QDRANT_API_KEY) in .env first.",
            file=sys.stderr,
        )
        return 1

    client = AsyncQdrantClient(
        url=settings.EVREN_QDRANT_URL, api_key=settings.EVREN_QDRANT_API_KEY
    )
    try:
        collections = (await client.get_collections()).collections
        if not collections:
            print(f"No collections found on {settings.EVREN_QDRANT_URL} -- nothing to do.")
            return 0

        print(f"Deleting {len(collections)} collection(s) on {settings.EVREN_QDRANT_URL}:")
        for collection in collections:
            print(f"  - {collection.name}")
            await client.delete_collection(collection.name)
        print("Done.")
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
