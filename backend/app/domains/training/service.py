"""Faz C3'ü (#187) düzenler: `feedback` oylarını `training_samples`'a
derlemek ve yeterince biriktiğinde bunları yenilenmiş bir `CompanyAdapter`
(Faz C2, #185) stil adaptörüne dönüştürmek.

Burası `app.ai.training`'in (saf derleyici/madenci) ve
`app.domains.companies.provider`'ın (C2 adaptörünün okuma/yazma katmanı)
buluştuğu tek yerdir -- ikisi de birbirini doğrudan import etmek yerine
burada birbirine bağlanır, her iki tarafın kendi sınırını da bozulmadan
tutar.

Bu dosyayı iki çok farklı yürütme şekli, türe göre paylaşır:

- `kind="style_adapter"` (`run_style_adapter_training`) tetikleyen isteğin
  içinde senkron çalışır -- yaptığı tek LLM çağrısı, birkaç saniye süren
  tek bir `style_miner.mine_style` çağrısıdır (bunun neden bir kuyruk
  gerektirmediği için #187'nin kendi gövdesine bakın).
- `kind="lora_sft"`/`"lora_dpo"` (`enqueue_lora_training_run`) gerçekten
  uzun sürer (bir GPU host'ta potansiyel olarak saatler), bu yüzden
  burada yalnızca *kuyruğa alınır* -- ayrı `worker` konteynerinde
  (Faz C3 Aşama 3, #191) çalışan `app.workers.training.
  run_lora_training_job` fiili işi yapar.
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
LORA_SFT_KIND = "lora_sft"
LORA_DPO_KIND = "lora_dpo"
LORA_KINDS = (LORA_SFT_KIND, LORA_DPO_KIND)


class TrainingService:
    def __init__(self, repository: TrainingRepository):
        self.repository = repository

    # ------------------------------------------------------------------
    # Derleme -- eğitimin kendisinden bağımsız, tek başına çalışabilir
    # (bkz. TrainingRepository/TrainingSampleModel docstring'leri: bu,
    # üzerinde herhangi bir şey eğitilmeden önce bilerek incelenebilir
    # tutulur).
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
        """Bir eğitim çalıştırmasının okuyacağı tam satırlar -- bunun ve
        eğitim yolunun neden tek bir sorguyu paylaştığı için
        `TrainingRepository.list_all_active_samples`'ın docstring'ine
        bakın."""
        return await self.repository.list_all_active_samples(company_id)

    async def active_pairs_for_training(self, company_id: str) -> List[PreferencePair]:
        """Her aktif örnek, geri `PreferencePair`'lere dönüştürülür -- hem
        stil-adaptörü madencisinin (Aşama 2) hem de LoRA export adımının
        (`app.workers.training`, Aşama 3, #191) fiilen eğitildiği veri."""
        samples = await self.repository.list_all_active_samples(company_id)
        return [_sample_to_pair(sample) for sample in samples]

    async def delete_sample(self, sample_id: str, company_id: str) -> TrainingSampleModel:
        sample = await self.repository.get_sample_by_id(sample_id, company_id)
        if sample is None:
            raise NotFoundException(message="Eğitim örneği bulunamadı.")
        await self.repository.soft_delete_sample(sample)
        return sample

    # ------------------------------------------------------------------
    # Eğitim çalıştırmaları
    # ------------------------------------------------------------------
    async def list_runs(self, company_id: str, skip: int = 0, limit: int = 100) -> List[TrainingRunModel]:
        return await self.repository.list_runs(company_id, skip=skip, limit=limit)

    async def count_runs(self, company_id: str) -> int:
        return await self.repository.count_runs(company_id)

    async def enqueue_lora_training_run(
        self, company_id: str, *, kind: str, triggered_by: Optional[str]
    ) -> TrainingRunModel:
        """`status="queued"` bir satır oluştur ve `arq` üzerinden eğitim
        worker'ına ver -- hemen döner, çalıştırmanın fiilen gerçekleşmesini
        beklemez (LoRA'nın senkron stil-adaptörü yolunun aksine neden
        kuyruğa alındığı için bu modülün kendi docstring'ine bakın).

        `app.workers.queue` importu üst düzey değil, yereldir: o modülün
        kendi `app.workers.training`'i, worker'ın kendisinin ihtiyaç
        duyduğu sorguyu çalıştırmak için `TrainingService`'i (bu sınıf)
        geri import eder -- burada üst düzey bir import iki modül arasında
        dairesel bir import olurdu. Bunu çağrı fiilen gerçekleşene kadar
        ertelemek, hiçbir tarafın bunun etrafında yeniden yapılanmasına
        gerek kalmadan döngüyü kırar.
        """
        from app.workers.queue import enqueue_lora_training_job

        run = await self.repository.create_run(
            company_id, kind=kind, triggered_by=triggered_by, trigger="manual", status="queued"
        )
        await enqueue_lora_training_job(company_id, run.id)
        return run

    async def run_style_adapter_training(
        self, company_id: str, *, triggered_by: Optional[str], llm_client
    ) -> TrainingRunModel:
        """Taze örnekler derle, ardından yeterli sinyal varsa güncellenmiş
        bir stil adaptörünü madencilikle çıkar ve yayınla.

        Tabloda o an her ne örnek varsa onun üzerinde eğitmek yerine her
        zaman önce yeniden derler, böylece bir çalıştırmanın
        `sample_count`'u bayat bir anlık görüntü değil, bu ana kadar
        verilen her oyu yansıtır.
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

            #: Otomatik çalıştırmalar preferred_examples'a asla dokunmaz --
            #: bunlar bir yöneticinin PUT .../adapter ile en son elle
            #: düzenlediği ne ise öyle kalır (bkz. set_company_adapter'ın
            #: docstring'i: tüm listeyi değiştirir, bu yüzden otomatik bir
            #: çalıştırma mevcut değeri açıkça ileri taşımalıdır, yoksa
            #: her seferinde onu sessizce siler).
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
        except Exception as exc:  # noqa: BLE001 -- başarısız bir çalıştırma isteğe fırlatılmak değil, görünür olmak zorunda
            logger.exception("Style adapter training run failed for company %s", company_id)
            return await self.repository.finish_run(
                run, status="failed", sample_count=None, error=str(exc)
            )


def _sample_to_pair(sample: TrainingSampleModel) -> PreferencePair:
    """Stil madencisi ORM satırlarını değil `PreferencePair`'leri okur --
    burası kalıcı hale getirilmiş bir `training_samples` satırının geri
    dönüştürüldüğü tek yerdir, böylece bir eğitim çalıştırması, ham geri
    bildirimden ikinci, potansiyel olarak farklı bir yeniden türetme
    yerine, az önce upsert ettiği tam satırlar üzerinden çalışır."""
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
