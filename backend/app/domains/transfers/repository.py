from typing import List, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.transfers.model.transfer_intent_model import ArtifactTransferIntentModel
from app.domains.transfers.model.transfer_model import ArtifactTransferModel


class ArtifactTransferRepository:
    """`artifact_transfers` için repository (bkz. `ArtifactTransferModel`).

    Her metot açık bir `company_id` alır, kiracılık (tenancy) işinden bu
    yana diğer her repository ile aynı kural -- RLS bunu destekler, yerini
    almaz.
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
        """Belirli bir belgenin her transferi, en yeniden en eskiye --
        `RecipientRecommendationService` tarafından belgenin zaten
        gönderildiği birinin tekrar önerilmesini önlemek için kullanılır."""
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
    """`artifact_transfer_intents` için repository (bkz.
    `ArtifactTransferIntentModel`) -- AI kanalının onay yaşam döngüsü.
    `cas_update`, tüm durum makinesinin
    (`app.domains.transfers.intent_service.TransferIntentService`)
    ilerlediği tek metottur: düz bir `UPDATE ... WHERE state IN
    (:expected)`, planın §I/§H'sine ("Confirmation güvenliği") göre
    tekrarlanan veya eskimiş bir onayı bir yarış durumu yerine "0 satır
    değişti"ye dönüştüren şeydir.
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
        """`intent_id`'nin `state`'ini, yalnızca hâlâ `expected_states`'ten
        biriyse, atomik olarak ilerletir.

        Returns:
            Koşullu `UPDATE` gerçekten bir satırla eşleştiğinde, satırın
            yeniden okunmuş hali; sıfır satırla eşleştiğinde `None` --
            çağıran (tekrarlanan bir resume, yarışan iki sekme veya
            eskimiş bir interrupt replay'i) bunu geçici bir hataymış gibi
            asla yeniden denememeli, "başka bir yerde zaten çözümlendi"
            olarak ele almalıdır.
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
