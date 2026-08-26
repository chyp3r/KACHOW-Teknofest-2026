"""arq job: LoRA/PEFT fine-tuning -- Faz C3, Aşama 3 (#191).

Yalnızca training worker container'ı içinde çalışır (`deploy/docker/worker.
Dockerfile`, `compose.yml`'ın `profiles: ["training"]` altındaki `worker`
servisi -- düz `docker compose up` ile asla başlatılmaz, yalnızca
`scripts/start_training_worker.sh` üzerinden). `app.domains.training.service.
run_style_adapter_training`'in aksine (bu, tetikleyen isteğin içinde eş
zamanlı çalışır -- deterministic-diff-artı-tek-LLM-çağrılı bir işin bunun
için neden yeterince ucuz olduğu için o modülün kendi docstring'ine bakın),
bir LoRA run'ı gerçekten uzundur (bir GPU host'ta potansiyel olarak
saatler sürebilir), bu yüzden bir isteği bloklamak yerine `arq`
(`app.workers.queue`) üzerinden kuyruğa alınır.

Her DB dokunuşu kendi kısa ömürlü `tenant_session`'ını açar; bu,
`app.domains.drafts.draft_recorder` ve `app.domains.companies.provider`'ın
istek dışı işler için zaten kullandığı aynı kuraldır -- bu fonksiyon,
istek kapsamlı herhangi bir `Depends(get_db)`'in tamamen dışında çalışır.
Bir `TrainingRunModel` örneği asla iki `tenant_session` bloğu arasında
*mutasyona uğramış* olarak taşınmaz (yalnızca zaten yüklenmiş düz sütunları,
kendi session'ı kapandıktan sonra okunur; ilişkisi olmadığından
`expire_on_commit=False` altında güvenlidir) -- ona yazmak her zaman önce
taze, session'a bağlı bir kopyayı yeniden getirir.
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

#: Ortalama shadow-eval güven skoru, mevcut modelinkinden bu kadar puandan
#: fazla düşen bir aday model regresyon olarak kabul edilir -- tam gerekçe
#: ve bilinçli olarak sınırlandırılmış tasarım için `_shadow_evaluate`'in
#: kendi docstring'ine bakın.
SHADOW_EVAL_REGRESSION_MARGIN = 5.0
#: Shadow eval'in kaç ayrılmış (held-out) derlenmiş örnek için taslak
#: ürettiği -- bilinçli olarak küçük, çünkü bu örnek başına canlı bir
#: Ollama sunucusunu iki kez çağırır (mevcut model + aday model).
SHADOW_EVAL_SAMPLE_SIZE = 20


async def run_lora_training_job(ctx: dict, company_id: str, run_id: str) -> Dict[str, Any]:
    """arq job fonksiyonunun kendisi -- `app.workers.queue.
    WorkerSettings.functions` içinde kayıtlıdır. `ctx`, arq'ın kendi
    iş-başına bağlamıdır (burada kullanılmaz, işler arası duruma gerek
    yoktur).

    Asla exception fırlatmaz: her başarısızlık yolu `training_runs.status`'u
    `error` ayarlanmış `"failed"` olarak günceller ve bir sonuç dict'i
    döner, böylece bir run'ın sonucu her zaman
    `GET /companies/{id}/training-runs` üzerinden görünür -- eş zamanlı
    style-adapter yolu için `run_style_adapter_training`'in zaten
    kurduğu aynı sözleşme.
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
        # Önce yeniden derle -- run_style_adapter_training'in kendi
        # docstring'iyle aynı gerekçe: bir run'ın sample_count'u eski bir
        # tablo anlık görüntüsünü değil, bu ana kadar verilmiş her oyu
        # yansıtmalıdır.
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
    """Adapter'ı, HTTP `/api/create` uç noktası üzerinden çalıştırılabilir
    bir Ollama modeli olarak yayınlar -- `ollama` CLI'ı değil. Bu worker
    container'ında yerel bir Ollama kurulumu yoktur; CLI de zaten Ollama'yı
    gerçekten çalıştıran host sürecine shell çağrısı yapardı (bunun dev'de
    neden bir compose servisi değil `host.docker.internal` olduğu için
    `settings.OLLAMA_BASE_URL`'in kendi docstring'ine bakın), bu yüzden
    HTTP API, Ollama'nın gerçekte nerede çalıştığından bağımsız olarak
    aynı şekilde çalışan tek yoldur.

    `adapter_dir`, Ollama *sunucu* sürecinin kendisinin okuyabileceği bir
    yol olmalıdır -- Ollama, bu worker'ın `TRAINING_ARTIFACTS_DIR`'a
    yazdığından farklı bir host/volume üzerinde çalışıyorsa, o dizinin
    ikisi arasında paylaşılan bir yol olması gerekir (örn. her iki tarafta
    da aynı bind mount). Bu, bu fonksiyonun sizin yerinize yapmadığı ve
    yapamayacağı bir dağıtım-topolojisi kararıdır.
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
    """Bir training run'ının aday modeli yayınlamasına izin vermeden önce,
    onu küçük bir ayrılmış (held-out) örnek üzerinde mevcut modelle
    karşılaştırır.

    Bilinçli olarak tam bir A/B taslak-kalitesi karşılaştırmasından
    sınırlandırılmıştır: `evaluation.harness.draft_suite`,
    *deterministik verifier*'ı sabit bir altın veri setine karşı ölçer
    (hiç model çağrısı yapmaz), bu yüzden iki modelin üretimlerini
    karşılaştıramaz -- bunun için mevcut bir harness yoktur. Bunun yerine
    bu fonksiyon, her ayrılmış örneğin `prompt_context`'inden oluşturulan
    düz bir talimatla her iki modeli de çalıştırır (tam üretim writer.md
    prompt'u değil -- onu sadakatle çoğaltmak burada kapsam dışıdır) ve
    her çıktıyı gerçek taslak pipeline'ının kullandığı aynı deterministik
    `verify_draft` ile puanlar. Yalnızca güven-skoru farkı karşılaştırılır
    -- çünkü hiçbir çağrının gerçek bir kaynak belgesi yoktur, temellendirme
    (groundedness) kontrolleri her iki taraf için de önemsizce geçer; farklı
    olan, stil-eğitimli bir modelin iyileştirmesi gereken, gerilememesi
    gereken gerçek bir sinyal olan yapısal/biçim skorudur.

    Karşılaştıracak ayrılmış örneği olmayan bir model (örn. her çiftin
    `chosen` tamamlaması eksik olduğunda) asla regresyon olarak
    işaretlenmez -- ona karşı kanıt yoktur ve hiç yayınlamayı reddetmek,
    elle yazılmış bir adapter'ın zaten yaptığı gibi güvene dayanarak
    yayınlamaktan daha kötü olurdu.
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
