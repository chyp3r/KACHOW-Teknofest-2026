"""The transfer-specific policy gate -- narrows what the PDP already permitted.

Mirrors `app.core.authz.engine`'s own shape (a pure decision object, no
raising) but is deliberately a separate, smaller layer: `TransferPolicy`
only ever *removes* permission the PDP already granted (self-send, an
inactive/deleted recipient, insufficient clearance, a missing favorite on
the AI channel) -- it never grants anything the PDP denied, and the two are
never allowed to disagree about who owns a "yes". See `ArtifactTransferService.
execute`'s own docstring for where this sits in the call order (PDP first,
this second).

Tenant matching is deliberately *not* one of this policy's own checks: by
the time `evaluate` runs, `recipient` was already loaded through
`UserRepository.get_by_id_in_company(recipient_id, company_id)` -- a
cross-tenant id resolves to `None` there and the caller raises
`NotFoundException` before policy is ever consulted, the same "RLS/company-
scoped lookup, not a business rule" pattern `PoolService`/`DraftShareService`
already use.
"""

from dataclasses import dataclass
from typing import Optional

from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.permissions.role_checker import clearance_for
from app.domains.units.repository import UnitMembershipRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserFavoriteRepository


@dataclass(frozen=True)
class TransferPolicyDecision:
    """The verdict `ArtifactTransferService.execute` acts on.

    Attributes:
        permit: Whether the transfer may proceed.
        reason_code: A short machine tag for the first failing check
            (`"self_transfer"`, `"recipient_inactive"`, `"clearance"`,
            `"favorite_required"`), or `None` when `permit` is True.
        message_tr: A ready-to-show Turkish explanation, or `None` when
            `permit` is True.
        cross_unit: Whether the recipient's primary unit differs from the
            artifact's own destination unit -- computed regardless of
            `permit`, since a caller building a confirmation prompt (Faz 4)
            needs this even when everything else about the transfer is
            fine.
    """

    permit: bool
    reason_code: Optional[str]
    message_tr: Optional[str]
    cross_unit: bool


class TransferPolicy:
    def __init__(
        self,
        unit_membership_repository: UnitMembershipRepository,
        favorite_repository: UserFavoriteRepository,
    ):
        self.unit_membership_repository = unit_membership_repository
        self.favorite_repository = favorite_repository

    async def evaluate(
        self,
        *,
        sender: UserModel,
        recipient: UserModel,
        company_id: str,
        channel: str,
        artifact_sensitivity: Optional[SensitivityLevel] = None,
        artifact_destination_unit_id: Optional[str] = None,
    ) -> TransferPolicyDecision:
        """Evaluate every deny rule in order, short-circuiting on the first hit.

        Args:
            sender: The authenticated caller, already PDP-authorized to
                transfer this specific artifact.
            recipient: The target user, already resolved within
                `company_id` (see this module's own docstring).
            company_id: Tenant scope, for the cross-unit/favorite lookups.
            channel: `"chat"` | `"ai"` | `"rest"` -- only `"ai"` requires
                the recipient to already be a favorite (see the plan's
                §2.3: the AI channel must not be able to send to someone
                the user never explicitly trusted enough to favorite;
                manual chat/REST sends carry no such requirement, since the
                human is directly choosing the recipient by hand).
            artifact_sensitivity: The document's confidentiality grade.
                `None` for a draft -- drafts carry no clearance concept in
                this system today, so the check is skipped entirely rather
                than compared against a manufactured default.
            artifact_destination_unit_id: The artifact's own routed unit
                (`drafts.destination_unit_id`), when it has one, for the
                cross-unit computation. `None` for a document (no
                equivalent concept exists on `DocumentModel` today) or an
                unrouted draft -- `cross_unit` then stays `False`, an
                honest "can't be computed" rather than a guess.

        Returns:
            A `TransferPolicyDecision`. `cross_unit` is always computed,
            even on a `permit=False` decision.
        """
        cross_unit = await self._compute_cross_unit(
            recipient.id, company_id, artifact_destination_unit_id
        )

        if recipient.id == sender.id:
            return TransferPolicyDecision(
                permit=False,
                reason_code="self_transfer",
                message_tr="Kendinize transfer yapamazsınız.",
                cross_unit=cross_unit,
            )

        if not recipient.is_active or recipient.is_deleted:
            return TransferPolicyDecision(
                permit=False,
                reason_code="recipient_inactive",
                message_tr="Alıcı artık aktif değil.",
                cross_unit=cross_unit,
            )

        if artifact_sensitivity is not None:
            recipient_clearance = clearance_for(recipient)
            if recipient_clearance is None or recipient_clearance < artifact_sensitivity:
                return TransferPolicyDecision(
                    permit=False,
                    reason_code="clearance",
                    message_tr="Alıcının gizlilik yetkisi bu evrak için yeterli değil.",
                    cross_unit=cross_unit,
                )

        if channel == "ai":
            is_favorite = await self.favorite_repository.is_favorite(
                sender.id, recipient.id, company_id
            )
            if not is_favorite:
                return TransferPolicyDecision(
                    permit=False,
                    reason_code="favorite_required",
                    message_tr=(
                        "AI üzerinden yalnızca favorilerinizdeki kişilere gönderim "
                        "yapılabilir. Önce bu kişiyi favorilerinize ekleyin."
                    ),
                    cross_unit=cross_unit,
                )

        return TransferPolicyDecision(permit=True, reason_code=None, message_tr=None, cross_unit=cross_unit)

    async def _compute_cross_unit(
        self, recipient_id: str, company_id: str, artifact_destination_unit_id: Optional[str]
    ) -> bool:
        if not artifact_destination_unit_id:
            return False
        primary = await self.unit_membership_repository.get_primary_for_user(recipient_id, company_id)
        if primary is None:
            return False
        return primary.unit_id != artifact_destination_unit_id
