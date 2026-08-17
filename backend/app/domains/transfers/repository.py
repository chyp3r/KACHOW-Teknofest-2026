from typing import List, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.transfers.model.transfer_intent_model import ArtifactTransferIntentModel
from app.domains.transfers.model.transfer_model import ArtifactTransferModel


class ArtifactTransferRepository:
    """Repository for `artifact_transfers` (see `ArtifactTransferModel`).

    Every method takes an explicit `company_id`, same convention as every
    other repository since the tenancy work -- RLS backs this up, it does
    not replace it.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, transfer_id: str, company_id: str) -> Optional[ArtifactTransferModel]:
        result = await self.db.execute(
            select(ArtifactTransferModel).where(
                ArtifactTransferModel.id == transfer_id, ArtifactTransferModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self, company_id: str, idempotency_key: str
    ) -> Optional[ArtifactTransferModel]:
        result = await self.db.execute(
            select(ArtifactTransferModel).where(
                ArtifactTransferModel.company_id == company_id,
                ArtifactTransferModel.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, transfer: ArtifactTransferModel) -> ArtifactTransferModel:
        self.db.add(transfer)
        await self.db.flush()
        return transfer

    async def list_for_artifact(
        self, company_id: str, artifact_kind: str, source_artifact_id: str
    ) -> List[ArtifactTransferModel]:
        """Every transfer of one specific artifact, newest first -- used by
        `RecipientRecommendationService` to avoid re-suggesting someone the
        artifact was already sent to."""
        result = await self.db.execute(
            select(ArtifactTransferModel)
            .where(
                ArtifactTransferModel.company_id == company_id,
                ArtifactTransferModel.artifact_kind == artifact_kind,
                ArtifactTransferModel.source_artifact_id == source_artifact_id,
            )
            .order_by(ArtifactTransferModel.created_at.desc())
        )
        return list(result.scalars().all())


class ArtifactTransferIntentRepository:
    """Repository for `artifact_transfer_intents` (see
    `ArtifactTransferIntentModel`) -- the AI channel's confirmation
    lifecycle. `cas_update` is the one method the whole state machine
    (`app.domains.transfers.intent_service.TransferIntentService`) advances
    through: a plain `UPDATE ... WHERE state IN (:expected)` is what turns a
    duplicate or stale confirmation into "0 rows changed" instead of a race,
    per the plan's §I/§H ("Confirmation güvenliği").
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, intent_id: str, company_id: str) -> Optional[ArtifactTransferIntentModel]:
        result = await self.db.execute(
            select(ArtifactTransferIntentModel).where(
                ArtifactTransferIntentModel.id == intent_id,
                ArtifactTransferIntentModel.company_id == company_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, intent: ArtifactTransferIntentModel) -> ArtifactTransferIntentModel:
        self.db.add(intent)
        await self.db.flush()
        return intent

    async def cas_update(
        self,
        intent_id: str,
        company_id: str,
        expected_states: Sequence[str],
        **values,
    ) -> Optional[ArtifactTransferIntentModel]:
        """Advance `intent_id`'s `state` only if it is still one of
        `expected_states`, atomically.

        Returns:
            The row, freshly re-read, when the conditional `UPDATE` actually
            matched a row; `None` when it matched zero -- the caller (a
            duplicate resume, two tabs racing, or a stale interrupt replay)
            must treat that as "already resolved elsewhere", never retry it
            as if it were a transient failure.
        """
        result = await self.db.execute(
            update(ArtifactTransferIntentModel)
            .where(
                ArtifactTransferIntentModel.id == intent_id,
                ArtifactTransferIntentModel.company_id == company_id,
                ArtifactTransferIntentModel.state.in_(expected_states),
            )
            .values(**values)
        )
        await self.db.flush()
        if result.rowcount != 1:
            return None
        return await self.get_by_id(intent_id, company_id)
