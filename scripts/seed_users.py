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

from app.domains.companies.seeder import seed_demo_company  # noqa: E402
from app.domains.units.seeder import seed_default_units  # noqa: E402
from app.domains.users.seeder import seed_default_users  # noqa: E402


async def main() -> int:
    # Mirrors app.lifespan's own seeding order exactly: users/units both
    # need the demo company's id, which seed_default_users' signature has
    # required since multi-tenancy landed -- calling it standalone (as this
    # script used to) raises TypeError.
    company_id = await seed_demo_company()
    await seed_default_users(company_id)
    if company_id is not None:
        await seed_default_units(company_id)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
