from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.engine import GrantView
from app.core.authz.model.permission_grant_model import PermissionGrantModel
from app.core.enums.user_role import UserRole


def _to_grant_view(row: PermissionGrantModel) -> GrantView:
    """Convert a persisted row into the DB-independent shape ``engine.py`` consumes."""
    return GrantView(
        id=row.id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        action=row.action,
        resource_type=row.resource_type,
        resource_selector=row.resource_selector or {},
        effect=row.effect,
        priority=row.priority,
        time_boxed=row.valid_from is not None or row.valid_until is not None,
    )


class PermissionGrantRepository:
    """Persistence for ``permission_grants`` -- the ABAC PDP's PAP store.

    Every method takes an explicit `company_id` and filters on it, same
    convention as every other repository since the tenancy work (see
    `app.domains.units.repository.UnitRepository`'s docstring).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active_for_subject(
        self, company_id: str, role: UserRole, user_id: str, action: str
    ) -> List[GrantView]:
        """Fetch every currently-active grant matching this subject and action.

        "Active" means: not revoked, and (no ``valid_from``/``valid_until``
        window, or the window covers ``now``). Matches grants targeting
        either ``subject_type="user"`` with this exact ``user_id``, or
        ``subject_type="role"`` with this ``role`` -- a role-typed grant
        applies to every member of that role, a user-typed grant to just
        one person. ``action`` may itself be ``"*"`` on a stored row (a
        blanket grant), so this also matches rows whose ``action`` column is
        the literal wildcard.
        """
        now = datetime.now(timezone.utc)
        stmt = select(PermissionGrantModel).where(
            PermissionGrantModel.company_id == company_id,
            PermissionGrantModel.action.in_((action, "*")),
            PermissionGrantModel.revoked_at.is_(None),
            or_(
                PermissionGrantModel.valid_from.is_(None),
                PermissionGrantModel.valid_from <= now,
            ),
            or_(
                PermissionGrantModel.valid_until.is_(None),
                PermissionGrantModel.valid_until >= now,
            ),
            or_(
                and_(
                    PermissionGrantModel.subject_type == "user",
                    PermissionGrantModel.subject_id == user_id,
                ),
                and_(
                    PermissionGrantModel.subject_type == "role",
                    PermissionGrantModel.subject_id == role.value,
                ),
            ),
        )
        result = await self.db.execute(stmt)
        return [_to_grant_view(row) for row in result.scalars().all()]

    async def list_for_user(self, company_id: str, user_id: str) -> List[PermissionGrantModel]:
        """Every non-revoked grant explicitly targeting ``user_id`` (role-typed grants excluded --
        this is "what was granted to this person specifically", for the ``GET /users/{id}/permissions``
        UI, not the full effective permission set)."""
        result = await self.db.execute(
            select(PermissionGrantModel).where(
                PermissionGrantModel.company_id == company_id,
                PermissionGrantModel.subject_type == "user",
                PermissionGrantModel.subject_id == user_id,
                PermissionGrantModel.revoked_at.is_(None),
            ).order_by(PermissionGrantModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, grant_id: str, company_id: str) -> Optional[PermissionGrantModel]:
        result = await self.db.execute(
            select(PermissionGrantModel).where(
                PermissionGrantModel.id == grant_id, PermissionGrantModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, grant: PermissionGrantModel) -> PermissionGrantModel:
        if not grant.id:
            grant.id = uuid4().hex
        self.db.add(grant)
        await self.db.flush()
        return grant

    async def revoke(self, grant_id: str, company_id: str) -> bool:
        """Mark a grant revoked (kept as its own audit trail, not deleted)."""
        grant = await self.get_by_id(grant_id, company_id)
        if grant is None or grant.revoked_at is not None:
            return False
        grant.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True
