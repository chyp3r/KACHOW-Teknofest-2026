"""Manually create the default ADMIN/MANAGER/EMPLOYEE accounts.

The API already runs this on every startup (see app.lifespan), so this
script exists only for on-demand use -- e.g. seeding a database that was
just migrated without restarting the running API process:

    docker compose run --rm backend python scripts/seed_users.py

Needs the `db` service reachable (unlike scripts/build_prototypes.py, don't
pass --no-deps).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domains.users.seeder import seed_default_users  # noqa: E402


async def main() -> int:
    await seed_default_users()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
