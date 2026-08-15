"""arq job: LoRA/PEFT fine-tuning -- Faz C3, Aşama 3 (#191).

Runs only inside the training worker container (`deploy/docker/worker.
Dockerfile`, `compose.yml`'s `worker` service under `profiles: ["training"]`
-- never started by plain `docker compose up`, only via
`scripts/start_training_worker.sh`). Unlike `app.domains.training.service.
run_style_adapter_training` (which runs synchronously inside the
triggering request -- see that module's own docstring for why a
deterministic-diff-plus-one-LLM-call job is cheap enough for that), a LoRA
run is genuinely long (potentially hours on a GPU host), so it is queued
via `arq` (`app.workers.queue`) instead of blocking a request.

Each DB touch opens its own short-lived `tenant_session`, same convention
`app.domains.drafts.draft_recorder` and `app.domains.companies.provider`
already use for out-of-request work -- this function runs entirely outside
any request-scoped `Depends(get_db)`. A `TrainingRunModel` instance is
never carried *mutated* across two `tenant_session` blocks (only its
already-loaded plain columns are read after its own session closes, safe
under `expire_on_commit=False` since it has no relationships) -- writing
to it always re-fetches a fresh, session-attached copy first.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

import httpx
from sqlalchemy import select

from app.ai.training import lora
from app.ai.training.dataset import PreferencePair
from app.ai.training.style_miner import MIN_FEEDBACK_SAMPLES
from app.ai.verification.draft_verifier import verify_draft
from app.core.config import settings
from app.domains.companies.model.company_model import CompanyModel
from app.domains.companies.provider import set_llm_model_override
from app.domains.training.repository import TrainingRepository
from app.domains.training.service import TrainingService
from app.infrastructure.database.session import tenant_session
from app.infrastructure.providers.ollama import OllamaClient

logger = logging.getLogger(__name__)

#: A candidate model whose average shadow-eval confidence score falls more
#: than this many points below the current model's is treated as a
#: regression -- see `_shadow_evaluate`'s own docstring for the full
#: reasoning and its deliberately scoped-down design.
SHADOW_EVAL_REGRESSION_MARGIN = 5.0
#: How many held-out compiled samples the shadow eval generates drafts for
#: -- small on purpose, since this calls a live Ollama server twice
#: (current model + candidate model) per sample.
SHADOW_EVAL_SAMPLE_SIZE = 20


async def run_lora_training_job(ctx: dict, company_id: str, run_id: str) -> Dict[str, Any]:
    """The arq job function itself -- registered in `app.workers.queue.
    WorkerSettings.functions`. `ctx` is arq's own per-job context (unused
    here, no cross-job state needed).

    Never raises: every failure path updates `training_runs.status` to
    `"failed"` with `error` set and returns a result dict, so a run's
    outcome is always visible via `GET /companies/{id}/training-runs` --
    the same contract `run_style_adapter_training` already establishes for
    the synchronous style-adapter path.
    """
    async with tenant_session(company_id, is_root=False) as session:
        repository = TrainingRepository(session)
        run = await repository.get_run_by_id(run_id, company_id)
        if run is None:
            logger.error("LoRA training job: run %s not found for company %s", run_id, company_id)
            return {"status": "not_found"}
        kind = run.kind

        result = await session.execute(select(CompanyModel).where(CompanyModel.id == company_id))
        company = result.scalar_one_or_none()
        if company is None:
            await repository.finish_run(run, status="failed", error="Şirket bulunamadı.")
            return {"status": "failed", "error": "company_not_found"}
        slug = company.slug
        await repository.start_run(run)

    try:
        return await _run_training(company_id=company_id, run_id=run_id, kind=kind, slug=slug)
    except Exception as exc:  # noqa: BLE001 -- must surface as a visible run status, not crash the worker
        logger.exception("LoRA training job failed for company %s run %s", company_id, run_id)
        async with tenant_session(company_id, is_root=False) as session:
            run = await TrainingRepository(session).get_run_by_id(run_id, company_id)
            if run is not None:
                await TrainingRepository(session).finish_run(run, status="failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


async def _run_training(*, company_id: str, run_id: str, kind: str, slug: str) -> Dict[str, Any]:
    async with tenant_session(company_id, is_root=False) as session:
        service = TrainingService(TrainingRepository(session))
        # Recompile first -- same reasoning as run_style_adapter_training's
        # own docstring: a run's sample_count should reflect every vote
        # cast up to this moment, not a stale table snapshot.
        await service.compile_samples(company_id, training_run_id=run_id)
        pairs = await service.active_pairs_for_training(company_id)

    examples = (
        lora.sft_examples_from_pairs(pairs)
        if kind == "lora_sft"
        else lora.dpo_examples_from_pairs(pairs)
    )

    if len(examples) < MIN_FEEDBACK_SAMPLES:
        async with tenant_session(company_id, is_root=False) as session:
            run = await TrainingRepository(session).get_run_by_id(run_id, company_id)
            await TrainingRepository(session).finish_run(
                run,
                status="skipped",
                sample_count=len(examples),
                metrics={"reason": "below_min_feedback_samples"},
            )
        return {"status": "skipped", "sample_count": len(examples)}

    run_dir = str(Path(settings.TRAINING_ARTIFACTS_DIR) / slug / run_id)
    jsonl_path = f"{run_dir}/{'sft' if kind == 'lora_sft' else 'dpo'}.jsonl"
    if kind == "lora_sft":
        lora.export_sft_jsonl(examples, jsonl_path)
    else:
        lora.export_dpo_jsonl(examples, jsonl_path)

    config = lora.LoraTrainingConfig(
        base_model=settings.OLLAMA_MODEL, output_dir=f"{run_dir}/adapter"
    )
    training_result = (
        lora.train_lora_sft(jsonl_path, config)
        if kind == "lora_sft"
        else lora.train_lora_dpo(jsonl_path, config)
    )

    model_name = f"kachow-{slug}:{run_id[:8]}"
    lora.write_ollama_modelfile(
        training_result.adapter_dir, settings.OLLAMA_MODEL, f"{run_dir}/Modelfile"
    )
    await _ollama_create(model_name, training_result.adapter_dir, settings.OLLAMA_MODEL)

    shadow = await _shadow_evaluate(
        pairs, current_model=settings.OLLAMA_MODEL, candidate_model=model_name
    )

    async with tenant_session(company_id, is_root=False) as session:
        repository = TrainingRepository(session)
        run = await repository.get_run_by_id(run_id, company_id)
        if shadow["regressed"]:
            await repository.finish_run(
                run,
                status="failed",
                sample_count=training_result.sample_count,
                error="Shadow değerlendirme regresyon tespit etti, yayına alınmadı.",
                metrics=shadow,
            )
            return {"status": "failed", **shadow}

        await set_llm_model_override(company_id, model_name)
        await repository.finish_run(
            run,
            status="succeeded",
            sample_count=training_result.sample_count,
            metrics={**shadow, "model_name": model_name, "artifact_path": training_result.adapter_dir},
        )
    return {"status": "succeeded", "model_name": model_name}


async def _ollama_create(model_name: str, adapter_dir: str, base_model: str) -> None:
    """Publish the adapter as a runnable Ollama model via the HTTP
    `/api/create` endpoint -- not the `ollama` CLI. This worker container
    has no local Ollama install; the CLI would also just shell out to
    whatever host process actually runs Ollama (see `settings.
    OLLAMA_BASE_URL`'s own docstring on why that is `host.docker.internal`
    in dev, not a compose service), so the HTTP API is the only path that
    works the same way regardless of where Ollama actually runs.

    `adapter_dir` must be a path the Ollama *server* process can itself
    read -- if Ollama runs on a different host/volume than this worker
    writes `TRAINING_ARTIFACTS_DIR` to, that directory needs to be a path
    shared between them (e.g. the same bind mount on both sides). That is
    a deployment-topology decision this function does not, and cannot,
    make for you.
    """
    modelfile = f"FROM {base_model}\nADAPTER {adapter_dir}\n"
    async with httpx.AsyncClient(base_url=settings.OLLAMA_BASE_URL, timeout=120.0) as client:
        response = await client.post(
            "/api/create", json={"model": model_name, "modelfile": modelfile}
        )
        response.raise_for_status()


async def _shadow_evaluate(
    pairs: List[PreferencePair], *, current_model: str, candidate_model: str
) -> Dict[str, Any]:
    """Compare the candidate model against the current one on a small
    held-out sample, before letting a training run publish it.

    Deliberately scoped down from a full A/B draft-quality comparison:
    `evaluation.harness.draft_suite` measures the *deterministic verifier*
    against a fixed gold set (no model call at all), so it cannot compare
    two models' generations -- there is no existing harness for that. This
    instead drives both models with a plain instruction built from each
    held-out sample's `prompt_context` (not the full production writer.md
    prompt -- replicating that faithfully is out of scope here) and scores
    each output with the same deterministic `verify_draft` the real draft
    pipeline uses. Only the confidence-score gap is compared -- since
    neither call has a real source document, groundedness checks trivially
    pass for both sides; what differs is the structural/format score,
    which *is* a real signal a style-trained model should improve, not
    regress.

    A model with no held-out samples to compare (e.g. every pair happened
    to lack a `chosen` completion) is never marked as a regression --
    there's no evidence against it, and refusing to ever publish would be
    worse than publishing on faith the way a hand-authored adapter already
    does.
    """
    held_out = [pair.chosen for pair in pairs if pair.chosen][:SHADOW_EVAL_SAMPLE_SIZE]
    if not held_out:
        return {"regressed": False, "sample_count": 0, "current_avg_score": None, "candidate_avg_score": None}

    current_client = OllamaClient(settings.OLLAMA_BASE_URL, model=current_model)
    candidate_client = OllamaClient(settings.OLLAMA_BASE_URL, model=candidate_model)

    current_scores: List[float] = []
    candidate_scores: List[float] = []
    for reference in held_out:
        prompt = (
            "Aşağıdaki örnek gibi resmî bir yazışma taslağı hazırla:\n\n" + reference[:400]
        )
        messages = [{"role": "user", "content": prompt}]
        current_draft = await current_client.generate(messages, temperature=0.3)
        candidate_draft = await candidate_client.generate(messages, temperature=0.3)
        current_scores.append(
            verify_draft(current_draft, strict=False).confidence_score
        )
        candidate_scores.append(
            verify_draft(candidate_draft, strict=False).confidence_score
        )

    current_avg = sum(current_scores) / len(current_scores)
    candidate_avg = sum(candidate_scores) / len(candidate_scores)
    return {
        "regressed": candidate_avg < current_avg - SHADOW_EVAL_REGRESSION_MARGIN,
        "sample_count": len(held_out),
        "current_avg_score": current_avg,
        "candidate_avg_score": candidate_avg,
    }
