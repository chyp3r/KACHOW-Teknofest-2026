"""Unit tests for TrainingService orchestration (Faz C3, #187) --
repository and companies.provider are both mocked, so these test only
compile/skip/succeed/fail branching, not real persistence (see the live
smoke test performed manually against real Postgres+Redis+Ollama for
that)."""

from unittest.mock import AsyncMock

import pytest

from app.ai.adapters.company_adapter import CompanyAdapter
from app.ai.training.dataset import FeedbackRecord, PreferencePair
from app.ai.training.style_miner import MIN_FEEDBACK_SAMPLES, MinedStyle
from app.api.exceptions.not_found import NotFoundException
from app.domains.training import service as service_module
from app.domains.training.model.training_run_model import TrainingRunModel
from app.domains.training.model.training_sample_model import TrainingSampleModel
from app.domains.training.service import TrainingService


def _sample(**overrides) -> TrainingSampleModel:
    fields = dict(
        id="sample-1",
        company_id="company-1",
        training_run_id=None,
        source="explicit_feedback",
        source_feedback_id="fb-1",
        source_draft_id="draft-1",
        prompt_context="",
        chosen="Sayın Makam,",
        rejected=None,
        weight=1.0,
        pair_hash="hash-1",
        used_in_runs=None,
        is_deleted=False,
    )
    fields.update(overrides)
    return TrainingSampleModel(**fields)


def _run(**overrides) -> TrainingRunModel:
    fields = dict(
        id="run-1", company_id="company-1", kind="style_adapter", status="running",
        triggered_by="user-1", trigger="manual", sample_count=None, metrics=None, error=None,
    )
    fields.update(overrides)
    return TrainingRunModel(**fields)


async def _apply_finish_run(run, *, status, sample_count=None, metrics=None, error=None):
    """Mimics TrainingRepository.finish_run's real mutate-and-return
    behavior -- a bare `lambda run, **kwargs: run` would leave `run`
    untouched, silently hiding whether the service passed the right status."""
    run.status = status
    run.sample_count = sample_count
    run.metrics = metrics
    run.error = error
    return run


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def service(repo):
    return TrainingService(repo)


# ==========================================
# compile_samples
# ==========================================
async def test_compile_samples_resolves_feedback_and_upserts_each_pair(service, repo):
    repo.resolvable_feedback.return_value = [
        FeedbackRecord(feedback_id="fb-1", signal="like", content="Sayın Makam,", draft_id="draft-1"),
        FeedbackRecord(feedback_id="fb-2", signal="dislike", content="selam", draft_id="draft-2"),
    ]
    repo.upsert_sample.side_effect = lambda company_id, pair, training_run_id=None: _sample(
        id=pair.source_feedback_id, source_feedback_id=pair.source_feedback_id,
        chosen=pair.chosen, rejected=pair.rejected, pair_hash=pair.pair_hash,
    )

    samples = await service.compile_samples("company-1")

    assert len(samples) == 2
    assert repo.upsert_sample.await_count == 2


async def test_compile_samples_skips_records_with_unresolvable_blank_text(service, repo):
    repo.resolvable_feedback.return_value = [
        FeedbackRecord(feedback_id="fb-1", signal="like", content="   ")
    ]

    samples = await service.compile_samples("company-1")

    assert samples == []
    repo.upsert_sample.assert_not_awaited()


# ==========================================
# delete_sample
# ==========================================
async def test_delete_sample_404s_when_missing(service, repo):
    repo.get_sample_by_id.return_value = None

    with pytest.raises(NotFoundException):
        await service.delete_sample("sample-1", "company-1")


async def test_delete_sample_soft_deletes_an_existing_row(service, repo):
    sample = _sample()
    repo.get_sample_by_id.return_value = sample

    result = await service.delete_sample("sample-1", "company-1")

    assert result is sample
    repo.soft_delete_sample.assert_awaited_once_with(sample)


# ==========================================
# stats
# ==========================================
async def test_stats_reports_remaining_gap_to_threshold(service, repo):
    repo.count_by_source.return_value = {"explicit_feedback": 12}

    result = await service.stats("company-1")

    assert result["total"] == 12
    assert result["min_samples_required"] == MIN_FEEDBACK_SAMPLES
    assert result["samples_remaining_to_threshold"] == MIN_FEEDBACK_SAMPLES - 12


async def test_stats_gap_never_goes_negative_once_past_threshold(service, repo):
    repo.count_by_source.return_value = {"explicit_feedback": MIN_FEEDBACK_SAMPLES + 10}

    result = await service.stats("company-1")

    assert result["samples_remaining_to_threshold"] == 0


# ==========================================
# run_style_adapter_training
# ==========================================
def _pairs(count: int) -> list[PreferencePair]:
    return [
        PreferencePair(
            source="explicit_feedback", source_feedback_id=f"fb-{i}", source_draft_id=None,
            prompt_context="", chosen="Sayın Makam," if i % 2 == 0 else None,
            rejected=None if i % 2 == 0 else "selam", weight=1.0, pair_hash=f"hash-{i}",
        )
        for i in range(count)
    ]


async def test_run_is_marked_skipped_below_the_minimum_sample_threshold(service, repo, monkeypatch):
    run = _run()
    repo.create_run.return_value = run
    repo.resolvable_feedback.return_value = [
        FeedbackRecord(feedback_id=f"fb-{i}", signal="like", content="Sayın Makam,")
        for i in range(MIN_FEEDBACK_SAMPLES - 1)
    ]
    repo.upsert_sample.side_effect = lambda company_id, pair, training_run_id=None: _sample(
        id=pair.source_feedback_id, source_feedback_id=pair.source_feedback_id,
        chosen=pair.chosen, rejected=pair.rejected, pair_hash=pair.pair_hash,
    )
    repo.finish_run.side_effect = _apply_finish_run

    mine_style = AsyncMock()
    monkeypatch.setattr(service_module, "mine_style", mine_style)

    result = await service.run_style_adapter_training(
        "company-1", triggered_by="user-1", llm_client=object()
    )

    assert result.status == "skipped"
    mine_style.assert_not_awaited()
    repo.finish_run.assert_awaited_once()
    assert repo.finish_run.await_args.kwargs["status"] == "skipped"


async def test_a_successful_run_preserves_existing_preferred_examples(service, repo, monkeypatch):
    """set_company_adapter replaces the whole preferred_examples list on
    every call -- an automated run must carry the current value forward or
    it would silently wipe an admin's hand-curated examples every time it
    runs (see TrainingService's own module docstring)."""
    run = _run()
    repo.create_run.return_value = run
    repo.resolvable_feedback.return_value = [
        FeedbackRecord(feedback_id=f"fb-{i}", signal="like", content="Sayın Makam,")
        for i in range(MIN_FEEDBACK_SAMPLES)
    ]
    repo.upsert_sample.side_effect = lambda company_id, pair, training_run_id=None: _sample(
        id=pair.source_feedback_id, source_feedback_id=pair.source_feedback_id,
        chosen=pair.chosen, rejected=pair.rejected, pair_hash=pair.pair_hash,
    )
    repo.finish_run.side_effect = _apply_finish_run

    monkeypatch.setattr(
        service_module,
        "mine_style",
        AsyncMock(return_value=MinedStyle(style_rules=("Kısa yaz.",), avoided_patterns=(), sample_count=MIN_FEEDBACK_SAMPLES)),
    )
    monkeypatch.setattr(
        service_module,
        "get_company_adapter",
        AsyncMock(
            return_value=CompanyAdapter(
                company_id="company-1", version=2, preferred_examples=("Elle eklenmiş örnek.",)
            )
        ),
    )
    set_adapter_mock = AsyncMock(
        return_value=CompanyAdapter(company_id="company-1", version=3, style_rules=("Kısa yaz.",))
    )
    monkeypatch.setattr(service_module, "set_company_adapter", set_adapter_mock)

    result = await service.run_style_adapter_training(
        "company-1", triggered_by="user-1", llm_client=object()
    )

    assert result.status == "succeeded"
    set_adapter_mock.assert_awaited_once()
    assert set_adapter_mock.await_args.kwargs["preferred_examples"] == ("Elle eklenmiş örnek.",)
    assert set_adapter_mock.await_args.kwargs["style_rules"] == ("Kısa yaz.",)


async def test_a_raised_exception_marks_the_run_failed_instead_of_propagating(service, repo, monkeypatch):
    run = _run()
    repo.create_run.return_value = run
    repo.resolvable_feedback.side_effect = RuntimeError("db down")
    repo.finish_run.side_effect = _apply_finish_run

    result = await service.run_style_adapter_training(
        "company-1", triggered_by="user-1", llm_client=object()
    )

    assert result.status == "failed"
    assert repo.finish_run.await_args.kwargs["error"] == "db down"


# ==========================================
# enqueue_lora_training_run (Faz C3 Aşama 3, #191)
# ==========================================
async def test_enqueue_lora_training_run_creates_a_queued_run_and_hands_it_to_arq(
    service, repo, monkeypatch
):
    run = _run(status="queued", kind="lora_sft")
    repo.create_run.return_value = run

    import app.workers.queue as queue_module

    enqueue_mock = AsyncMock(return_value="arq-job-1")
    monkeypatch.setattr(queue_module, "enqueue_lora_training_job", enqueue_mock)

    result = await service.enqueue_lora_training_run(
        "company-1", kind="lora_sft", triggered_by="user-1"
    )

    assert result is run
    repo.create_run.assert_awaited_once_with(
        "company-1", kind="lora_sft", triggered_by="user-1", trigger="manual", status="queued"
    )
    enqueue_mock.assert_awaited_once_with("company-1", run.id)


async def test_enqueue_lora_training_run_never_runs_the_job_itself_synchronously(
    service, repo, monkeypatch
):
    """The whole point of queuing: the request that triggers this must
    return immediately, regardless of whether any worker is even running
    to pick the job up."""
    run = _run(status="queued", kind="lora_dpo")
    repo.create_run.return_value = run

    import app.workers.queue as queue_module

    enqueue_mock = AsyncMock(return_value="arq-job-2")
    monkeypatch.setattr(queue_module, "enqueue_lora_training_job", enqueue_mock)

    await service.enqueue_lora_training_run("company-1", kind="lora_dpo", triggered_by="user-1")

    repo.finish_run.assert_not_awaited()
