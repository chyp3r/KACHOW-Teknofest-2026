"""Unit tests for app.workers.training.run_lora_training_job (Faz C3
Aşama 3, #191).

Same isolation strategy as test_company_provider.py: tenant_session is
stood in for with a fake context manager around a single shared mock
session, and every DB-facing class (TrainingRepository/TrainingService)
plus every heavy step (lora.*, _ollama_create, _shadow_evaluate,
set_llm_model_override) is a mock -- these tests are about the job
function's own control flow (found/not-found, skip threshold, success,
shadow-eval regression, exception -> failed), not real training or real
Postgres/Ollama.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.training.dataset import PreferencePair
from app.workers import training as training_module


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc_info):
        return False


def _run(**overrides) -> MagicMock:
    run = MagicMock()
    fields = dict(id="run-1", kind="lora_sft", status="queued")
    fields.update(overrides)
    for key, value in fields.items():
        setattr(run, key, value)
    return run


def _pair(chosen="Sayın Makam,", index=0) -> PreferencePair:
    return PreferencePair(
        source="explicit_feedback", source_feedback_id=f"fb-{index}", source_draft_id=None,
        prompt_context=f"context-{index}", chosen=chosen, rejected=None, weight=1.0,
        pair_hash=f"hash-{index}",
    )


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def fake_repo():
    repo = AsyncMock()
    repo.finish_run.side_effect = lambda run, **kwargs: run
    return repo


@pytest.fixture
def fake_service():
    service = AsyncMock()
    return service


@pytest.fixture(autouse=True)
def _patch_infra(monkeypatch, mock_session, fake_repo, fake_service):
    monkeypatch.setattr(training_module, "tenant_session", lambda *a, **k: _FakeSessionContext(mock_session))
    monkeypatch.setattr(training_module, "TrainingRepository", lambda session: fake_repo)
    monkeypatch.setattr(training_module, "TrainingService", lambda repo: fake_service)
    monkeypatch.setattr(training_module, "set_llm_model_override", AsyncMock())
    monkeypatch.setattr(training_module, "_ollama_create", AsyncMock())
    monkeypatch.setattr(
        training_module,
        "_shadow_evaluate",
        AsyncMock(return_value={"regressed": False, "sample_count": 1, "current_avg_score": 90, "candidate_avg_score": 92}),
    )


def _company_scalar_result(company):
    result = MagicMock()
    result.scalar_one_or_none.return_value = company
    return result


async def test_returns_not_found_when_the_run_is_missing(fake_repo, mock_session):
    fake_repo.get_run_by_id.return_value = None

    result = await training_module.run_lora_training_job({}, "company-1", "run-1")

    assert result == {"status": "not_found"}
    fake_repo.start_run.assert_not_called()


async def test_finishes_failed_when_the_company_is_missing(fake_repo, mock_session):
    fake_repo.get_run_by_id.return_value = _run()
    mock_session.execute.return_value = _company_scalar_result(None)

    result = await training_module.run_lora_training_job({}, "company-1", "run-1")

    assert result["status"] == "failed"
    fake_repo.finish_run.assert_awaited_once()
    assert fake_repo.finish_run.await_args.kwargs["status"] == "failed"


async def test_below_threshold_examples_are_skipped(monkeypatch, fake_repo, fake_service, mock_session):
    fake_repo.get_run_by_id.return_value = _run(kind="lora_sft")
    company = MagicMock(slug="acme")
    mock_session.execute.return_value = _company_scalar_result(company)
    fake_service.active_pairs_for_training.return_value = [_pair()]
    monkeypatch.setattr(training_module.lora, "sft_examples_from_pairs", lambda pairs: [])

    result = await training_module.run_lora_training_job({}, "company-1", "run-1")

    assert result["status"] == "skipped"
    fake_repo.start_run.assert_called_once()
    finish_calls = [c for c in fake_repo.finish_run.await_args_list]
    assert finish_calls[-1].kwargs["status"] == "skipped"


async def test_a_successful_run_publishes_the_model_override(
    monkeypatch, fake_repo, fake_service, mock_session, tmp_path
):
    fake_repo.get_run_by_id.return_value = _run(kind="lora_sft")
    company = MagicMock(slug="acme")
    mock_session.execute.return_value = _company_scalar_result(company)
    fake_service.active_pairs_for_training.return_value = [_pair(index=i) for i in range(60)]

    monkeypatch.setattr(training_module, "settings", MagicMock(TRAINING_ARTIFACTS_DIR=str(tmp_path), OLLAMA_MODEL="qwen3.5:9b", OLLAMA_BASE_URL="http://ollama"))
    monkeypatch.setattr(training_module.lora, "sft_examples_from_pairs", lambda pairs: [MagicMock()] * 60)
    monkeypatch.setattr(training_module.lora, "export_sft_jsonl", lambda examples, path: len(examples))
    monkeypatch.setattr(
        training_module.lora,
        "train_lora_sft",
        lambda path, config: training_module.lora.LoraTrainingResult(
            adapter_dir=f"{config.output_dir}", sample_count=60, final_loss=0.1
        ),
    )
    monkeypatch.setattr(training_module.lora, "write_ollama_modelfile", lambda *a, **k: "Modelfile")

    result = await training_module.run_lora_training_job({}, "company-1", "run-1")

    assert result["status"] == "succeeded"
    assert result["model_name"].startswith("kachow-acme:")
    training_module.set_llm_model_override.assert_awaited_once()
    override_args = training_module.set_llm_model_override.await_args.args
    assert override_args[0] == "company-1"
    assert override_args[1] == result["model_name"]
    finish_calls = fake_repo.finish_run.await_args_list
    assert finish_calls[-1].kwargs["status"] == "succeeded"


async def test_a_shadow_eval_regression_fails_the_run_without_publishing(
    monkeypatch, fake_repo, fake_service, mock_session, tmp_path
):
    fake_repo.get_run_by_id.return_value = _run(kind="lora_sft")
    company = MagicMock(slug="acme")
    mock_session.execute.return_value = _company_scalar_result(company)
    fake_service.active_pairs_for_training.return_value = [_pair(index=i) for i in range(60)]

    monkeypatch.setattr(training_module, "settings", MagicMock(TRAINING_ARTIFACTS_DIR=str(tmp_path), OLLAMA_MODEL="qwen3.5:9b", OLLAMA_BASE_URL="http://ollama"))
    monkeypatch.setattr(training_module.lora, "sft_examples_from_pairs", lambda pairs: [MagicMock()] * 60)
    monkeypatch.setattr(training_module.lora, "export_sft_jsonl", lambda examples, path: len(examples))
    monkeypatch.setattr(
        training_module.lora,
        "train_lora_sft",
        lambda path, config: training_module.lora.LoraTrainingResult(
            adapter_dir=config.output_dir, sample_count=60, final_loss=0.1
        ),
    )
    monkeypatch.setattr(training_module.lora, "write_ollama_modelfile", lambda *a, **k: "Modelfile")
    monkeypatch.setattr(
        training_module,
        "_shadow_evaluate",
        AsyncMock(return_value={"regressed": True, "sample_count": 20, "current_avg_score": 90, "candidate_avg_score": 60}),
    )

    result = await training_module.run_lora_training_job({}, "company-1", "run-1")

    assert result["status"] == "failed"
    training_module.set_llm_model_override.assert_not_awaited()
    finish_calls = fake_repo.finish_run.await_args_list
    assert finish_calls[-1].kwargs["status"] == "failed"
    assert "regresyon" in finish_calls[-1].kwargs["error"].lower()


async def test_an_unexpected_exception_marks_the_run_failed_instead_of_crashing_the_worker(
    fake_repo, fake_service, mock_session
):
    fake_repo.get_run_by_id.return_value = _run(kind="lora_sft")
    company = MagicMock(slug="acme")
    mock_session.execute.return_value = _company_scalar_result(company)
    fake_service.active_pairs_for_training.side_effect = RuntimeError("db down")

    result = await training_module.run_lora_training_job({}, "company-1", "run-1")

    assert result["status"] == "failed"
    assert result["error"] == "db down"
    finish_calls = fake_repo.finish_run.await_args_list
    assert finish_calls[-1].kwargs["status"] == "failed"
