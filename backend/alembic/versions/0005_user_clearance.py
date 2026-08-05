"""Add users.clearance_level: the per-employee confidentiality ceiling.

Mirrors the new column on app.domains.users.model.user_model.UserModel.
ADMIN/MANAGER clear every level by role alone (see
app.ai.policy.schema.GuardrailPolicy.role_clearance_map); this column only
matters for EMPLOYEE, whose ceiling is not fixed by role -- two employees can
legitimately need different access, so it's an individually-set field rather
than a second role tier. Defaults every existing row to "hizmete_ozel",
matching UserModel.clearance_level's own column default and
GuardrailPolicy.role_clearance_map[UserRole.EMPLOYEE] -- the same starting
point a brand-new employee gets, applied retroactively so no existing
account silently loses access it had under the pre-RBAC open-demo behaviour.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "clearance_level", sa.String(), nullable=False, server_default="hizmete_ozel"
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "clearance_level")
