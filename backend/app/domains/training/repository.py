from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.training.dataset import FeedbackRecord, PreferencePair
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.feedback.model.feedback_model import FeedbackModel
from app.domains.training.model.training_run_model import TrainingRunModel
from app.domains.training.model.training_sample_model import TrainingSampleModel


class TrainingRepository:
    """Repository for `training_samples`/`training_runs` (Faz C3, #187).

    Every method takes an explicit `company_id`, same convention as
    `FeedbackRepository` -- RLS backs this up, it does not replace it.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Reading raw signal to compile from
    # ------------------------------------------------------------------
    async def resolvable_feedback(self, company_id: str) -> List[FeedbackRecord]:
        """Every undeleted vote in `company_id` whose rated text could be
        resolved back to a `drafts` row via `feedback.draft_id` (see
        `FeedbackModel`'s docstring on why that is the only durable text
        store a vote can point back to). No FK backs `draft_id` -- the
        join condition here is the only place that relationship is
        expressed, same looseness `FeedbackModel.draft_id` itself
        documents.
        """
        query = (
            select(
                FeedbackModel.id,
                FeedbackModel.signal,
                FeedbackModel.draft_id,
                DraftModel.content,
                DraftModel.correspondence_type,
                DraftModel.confidence_score,
            )
            .join(DraftModel, DraftModel.id == FeedbackModel.draft_id)
            .where(
                FeedbackModel.company_id == company_id,
                FeedbackModel.is_deleted.is_(False),
                DraftModel.company_id == company_id,
                DraftModel.is_deleted.is_(False),
            )
        )
        result = await self.db.execute(query)
        return [
            FeedbackRecord(
                feedback_id=row.id,
                signal=row.signal,
                content=row.content,
                draft_id=row.draft_id,
                correspondence_type=row.correspondence_type,
                confidence_score=row.confidence_score,
            )
            for row in result.all()
        ]

    # ------------------------------------------------------------------
    # training_samples
    # ------------------------------------------------------------------
    async def get_sample_by_pair_hash(
        self, company_id: str, pair_hash: str
    ) -> Optional[TrainingSampleModel]:
        result = await self.db.execute(
            select(TrainingSampleModel).where(
                TrainingSampleModel.company_id == company_id,
                TrainingSampleModel.pair_hash == pair_hash,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_sample(
        self, company_id: str, pair: PreferencePair, training_run_id: Optional[str] = None
    ) -> TrainingSampleModel:
        """Insert a fresh row, or refresh an existing one in place (the
        content changes if the underlying vote flipped signal, see
        `dataset.pair_hash`'s docstring) -- a re-compile is always
        idempotent per pair identity."""
        existing = await self.get_sample_by_pair_hash(company_id, pair.pair_hash)
        if existing is not None:
            existing.prompt_context = pair.prompt_context
            existing.chosen = pair.chosen
            existing.rejected = pair.rejected
            existing.weight = pair.weight
            existing.is_deleted = False
            if training_run_id is not None:
                existing.training_run_id = training_run_id
            await self.db.flush()
            return existing

        sample = TrainingSampleModel(
            id=uuid4().hex,
            company_id=company_id,
            training_run_id=training_run_id,
            source=pair.source,
            source_feedback_id=pair.source_feedback_id,
            source_draft_id=pair.source_draft_id,
            prompt_context=pair.prompt_context,
            chosen=pair.chosen,
            rejected=pair.rejected,
            weight=pair.weight,
            pair_hash=pair.pair_hash,
        )
        self.db.add(sample)
        await self.db.flush()
        return sample

    async def get_sample_by_id(
        self, sample_id: str, company_id: str
    ) -> Optional[TrainingSampleModel]:
        result = await self.db.execute(
            select(TrainingSampleModel).where(
                TrainingSampleModel.id == sample_id,
                TrainingSampleModel.company_id == company_id,
                TrainingSampleModel.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_samples(
        self, company_id: str, source: Optional[str] = None, skip: int = 0, limit: int = 100
    ) -> List[TrainingSampleModel]:
        query = select(TrainingSampleModel).where(
            TrainingSampleModel.company_id == company_id, TrainingSampleModel.is_deleted.is_(False)
        )
        if source is not None:
            query = query.where(TrainingSampleModel.source == source)
        query = query.order_by(TrainingSampleModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_samples(self, company_id: str, source: Optional[str] = None) -> int:
        query = select(func.count(TrainingSampleModel.id)).where(
            TrainingSampleModel.company_id == company_id, TrainingSampleModel.is_deleted.is_(False)
        )
        if source is not None:
            query = query.where(TrainingSampleModel.source == source)
        result = await self.db.execute(query)
        return result.scalar_one()

    async def list_all_active_samples(self, company_id: str) -> List[TrainingSampleModel]:
        """Every undeleted sample, no pagination -- what a training run
        actually reads, and what `.../training-samples/export` streams:
        deliberately the same query, so shown data and trained data can
        never drift apart."""
        result = await self.db.execute(
            select(TrainingSampleModel)
            .where(TrainingSampleModel.company_id == company_id, TrainingSampleModel.is_deleted.is_(False))
            .order_by(TrainingSampleModel.created_at.asc())
        )
        return list(result.scalars().all())

    async def count_by_source(self, company_id: str) -> dict:
        query = (
            select(TrainingSampleModel.source, func.count(TrainingSampleModel.id))
            .where(TrainingSampleModel.company_id == company_id, TrainingSampleModel.is_deleted.is_(False))
            .group_by(TrainingSampleModel.source)
        )
        result = await self.db.execute(query)
        return {source: count for source, count in result.all()}

    async def soft_delete_sample(self, sample: TrainingSampleModel) -> None:
        sample.is_deleted = True
        await self.db.flush()

    async def mark_samples_used(self, samples: List[TrainingSampleModel], training_run_id: str) -> None:
        for sample in samples:
            used = list(sample.used_in_runs or [])
            if training_run_id not in used:
                used.append(training_run_id)
            sample.used_in_runs = used
        await self.db.flush()

    # ------------------------------------------------------------------
    # training_runs
    # ------------------------------------------------------------------
    async def create_run(
        self, company_id: str, *, kind: str, triggered_by: Optional[str], trigger: str = "manual"
    ) -> TrainingRunModel:
        run = TrainingRunModel(
            id=uuid4().hex,
            company_id=company_id,
            kind=kind,
            status="running",
            triggered_by=triggered_by,
            trigger=trigger,
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(run)
        await self.db.flush()
        return run

    async def finish_run(
        self,
        run: TrainingRunModel,
        *,
        status: str,
        sample_count: Optional[int] = None,
        metrics: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> TrainingRunModel:
        run.status = status
        run.sample_count = sample_count
        run.metrics = metrics
        run.error = error
        run.finished_at = datetime.now(timezone.utc)
        await self.db.flush()
        return run

    async def get_run_by_id(self, run_id: str, company_id: str) -> Optional[TrainingRunModel]:
        result = await self.db.execute(
            select(TrainingRunModel).where(
                TrainingRunModel.id == run_id, TrainingRunModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def list_runs(self, company_id: str, skip: int = 0, limit: int = 100) -> List[TrainingRunModel]:
        result = await self.db.execute(
            select(TrainingRunModel)
            .where(TrainingRunModel.company_id == company_id)
            .order_by(TrainingRunModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_runs(self, company_id: str) -> int:
        result = await self.db.execute(
            select(func.count(TrainingRunModel.id)).where(TrainingRunModel.company_id == company_id)
        )
        return result.scalar_one()
