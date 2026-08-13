"""Add units: the routable department list, previously hardcoded.

Mirrors app.domains.units.model.unit_model.UnitModel. Before this, the
routing destinations came from a frozen Python tuple
(`RoutingPolicy.units`) duplicated across policy, a Pydantic `Literal` and a
prompt template -- changing a unit needed a code change and a deploy.
Managers now create/describe/disable units through `POST /units` etc, and
`routing_graph` reads the active set fresh on every routing decision (see
`app.domains.units.provider.get_active_units_for_routing`).

No data is seeded here -- `app.domains.units.seeder.seed_default_units` does
that idempotently at app boot, same as `app.domains.users.seeder` does for
the default accounts, so a fresh environment isn't left with an empty unit
list.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "units",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_units_name"),
    )
    op.create_index("ix_units_id", "units", ["id"])
    op.create_index("ix_units_name", "units", ["name"])


def downgrade() -> None:
    op.drop_index("ix_units_name", table_name="units")
    op.drop_index("ix_units_id", table_name="units")
    op.drop_table("units")
