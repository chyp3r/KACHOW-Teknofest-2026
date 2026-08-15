"""Orchestrates Faz C3 (#187): compiling `feedback` votes into
`training_samples`, and turning enough of them into a refreshed
`CompanyAdapter` (Faz C2, #185) style adapter.

This is the one place `app.ai.training` (pure compiler/miner) and
`app.domains.companies.provider` (the C2 adapter's read/write layer) meet
-- both are wired together here rather than either importing the other
directly, keeping each side's own boundary intact.

Runs synchronously inside the request that triggered them: the only LLM
call this phase makes is the single `style_miner.mine_style` call, which
takes a few seconds -- see #187's own body for why that does not warrant
an `arq` worker yet.
"""

import logging
from typing import List, Optional

from app.ai.training.dataset import PreferencePair, compile_pairs_from_feedback
from app.ai.training.style_miner import MIN_FEEDBACK_SAMPLES, mine_style
from app.api.exceptions.not_found import NotFoundException
from app.domains.companies.provider import get_company_adapter, set_company_adapter
from app.domains.training.model.training_run_model import TrainingRunModel
from app.domains.training.model.training_sample_model import TrainingSampleModel
from app.domains.training.repository import TrainingRepository

logger = logging.getLogger(__name__)

STYLE_ADAPTER_KIND = "style_adapter"


class TrainingService:
    def __init__(self, repository: TrainingRepository):
        self.repository = repository

    # ------------------------------------------------------------------
    # Compilation -- can run standalone, independent of training itself
    # (see TrainingRepository/TrainingSampleModel docstrings: this is
    # deliberately inspectable before anything is trained on it).
    # ------------------------------------------------------------------
    async def compile_samples(
        self, company_id: str, training_run_id: Optional[str] = None
    ) -> List[TrainingSampleModel]:
        records = await self.repository.resolvable_feedback(company_id)
        pairs = compile_pairs_from_feedback(company_id, records)
        samples = [
            await self.repository.upsert_sample(company_id, pair, training_run_id=training_run_id)
            for pair in pairs
        ]
        return samples

    async def list_samples(
        self, company_id: str, source: Optional[str] = None, skip: int = 0, limit: int = 100
    ) -> List[TrainingSampleModel]:
        return await self.repository.list_samples(company_id, source, skip=skip, limit=limit)

    async def count_samples(self, company_id: str, source: Optional[str] = None) -> int:
        return await self.repository.count_samples(company_id, source)

    async def stats(self, company_id: str) -> dict:
        by_source = await self.repository.count_by_source(company_id)
        total = sum(by_source.values())
        remaining = max(0, MIN_FEEDBACK_SAMPLES - total)
        return {
            "total": total,
            "by_source": by_source,
            "min_samples_required": MIN_FEEDBACK_SAMPLES,
            "samples_remaining_to_threshold": remaining,
        }

    async def export_samples(self, company_id: str) -> List[TrainingSampleModel]:
        """The exact rows a training run would read -- see
        `TrainingRepository.list_all_active_samples`'s docstring for why
        this and the training path share one query."""
        return await self.repository.list_all_active_samples(company_id)

    async def delete_sample(self, sample_id: str, company_id: str) -> TrainingSampleModel:
        sample = await self.repository.get_sample_by_id(sample_id, company_id)
        if sample is None:
            raise NotFoundException(message="Eğitim örneği bulunamadı.")
        await self.repository.soft_delete_sample(sample)
        return sample

    # ------------------------------------------------------------------
    # Training runs
    # ------------------------------------------------------------------
    async def list_runs(self, company_id: str, skip: int = 0, limit: int = 100) -> List[TrainingRunModel]:
        return await self.repository.list_runs(company_id, skip=skip, limit=limit)

    async def count_runs(self, company_id: str) -> int:
        return await self.repository.count_runs(company_id)

    async def run_style_adapter_training(
        self, company_id: str, *, triggered_by: Optional[str], llm_client
    ) -> TrainingRunModel:
        """Compile fresh samples, then mine and publish an updated style
        adapter if there is enough signal.

        Always recompiles first (rather than training on whatever samples
        already happen to be in the table) so a run's `sample_count`
        reflects every vote cast up to this moment, not a stale snapshot.
        """
        run = await self.repository.create_run(
            company_id, kind=STYLE_ADAPTER_KIND, triggered_by=triggered_by
        )
        try:
            samples = await self.compile_samples(company_id, training_run_id=run.id)
            pairs = [_sample_to_pair(sample) for sample in samples]

            if len(pairs) < MIN_FEEDBACK_SAMPLES:
                return await self.repository.finish_run(
                    run,
                    status="skipped",
                    sample_count=len(pairs),
                    metrics={"reason": "below_min_feedback_samples"},
                )

            mined = await mine_style(llm_client, pairs)
            if mined is None:
                return await self.repository.finish_run(
                    run,
                    status="skipped",
                    sample_count=len(pairs),
                    metrics={"reason": "below_min_feedback_samples"},
                )

            #: Automated runs never touch preferred_examples -- those stay
            #: whatever an admin last hand-curated via PUT .../adapter (see
            #: set_company_adapter's docstring: it replaces the whole list,
            #: so an automated run has to explicitly carry the current
            #: value forward or it would silently wipe it every time).
            current_adapter = await get_company_adapter(company_id)
            adapter = await set_company_adapter(
                company_id,
                style_rules=mined.style_rules,
                preferred_examples=current_adapter.preferred_examples,
                avoided_patterns=mined.avoided_patterns,
                sample_count=mined.sample_count,
            )
            await self.repository.mark_samples_used(samples, run.id)
            return await self.repository.finish_run(
                run,
                status="succeeded",
                sample_count=mined.sample_count,
                metrics={
                    "adapter_version": adapter.version,
                    "style_rules_count": len(adapter.style_rules),
                    "avoided_patterns_count": len(adapter.avoided_patterns),
                },
            )
        except Exception as exc:  # noqa: BLE001 -- a failed run must be visible, not raised into the request
            logger.exception("Style adapter training run failed for company %s", company_id)
            return await self.repository.finish_run(
                run, status="failed", sample_count=None, error=str(exc)
            )


def _sample_to_pair(sample: TrainingSampleModel) -> PreferencePair:
    """The style miner reads `PreferencePair`s, not ORM rows -- this is the
    one place a persisted `training_samples` row is converted back, so a
    training run works from the exact rows it just upserted rather than a
    second, potentially different, re-derivation from raw feedback."""
    return PreferencePair(
        source=sample.source,
        source_feedback_id=sample.source_feedback_id,
        source_draft_id=sample.source_draft_id,
        prompt_context=sample.prompt_context or "",
        chosen=sample.chosen,
        rejected=sample.rejected,
        weight=sample.weight,
        pair_hash=sample.pair_hash,
    )
