from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
