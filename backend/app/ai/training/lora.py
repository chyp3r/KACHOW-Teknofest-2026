"""LoRA/PEFT fine-tuning -- Faz C3, Aşama 3 (#191).

`torch`/`datasets`/`peft`/`transformers`/`trl` tembel (lazy) olarak import
edilir: bunlar yalnızca training worker'ın image'ında bulunur
(`requirements-training.txt`), asla ana backend'de değil. Bu modülü import
etmek (ör. dolaylı olarak, çünkü tek gerçek çağıran `app.workers.training`)
aşağıdaki fonksiyonları hiç çağırmayan bir süreçte sadece bu paketler
bulunmuyor diye asla başarısız olmamalıdır -- yalnızca `train_lora_sft`/
`train_lora_dpo`'yu bunlar kurulu olmadan gerçekten çağırmak net bir
`RuntimeError` fırlatır. Import başarısız olduğunda normalde bu import'lardan
gelecek her isim yine de (`None`'a) bağlanır, böylece testler paketler
mevcut olmadan bunları monkeypatch edebilir.

`app.ai.training.dataset`'in belgelediği aynı kural gereği burada da
`app.domains` import'u yok: `app.workers.training`, `PreferencePair`ları
DB'den çözümler ve bu modüle düz veri olarak aktarır.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.ai.training.dataset import PreferencePair

logger = logging.getLogger(__name__)

try:
    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import DPOConfig, DPOTrainer, SFTConfig, SFTTrainer

    _TRAINING_LIBS_AVAILABLE = True
except ImportError:
    torch = None
    Dataset = None
    LoraConfig = PeftModel = get_peft_model = None
    AutoModelForCausalLM = AutoTokenizer = None
    DPOConfig = DPOTrainer = SFTConfig = SFTTrainer = None
    _TRAINING_LIBS_AVAILABLE = False


def _require_training_libs() -> None:
    if not _TRAINING_LIBS_AVAILABLE:
        raise RuntimeError(
            "LoRA eğitim kütüphaneleri (torch/transformers/peft/trl/datasets) yüklü "
            "değil -- bu fonksiyon yalnızca requirements-training.txt kurulu training "
            "worker image'ında çalıştırılabilir (bkz. deploy/docker/worker.Dockerfile)."
        )


def _dtype():
    return torch.bfloat16 if torch.cuda.is_available() else torch.float32


@dataclass(frozen=True)
class SftExample:
    prompt: str
    completion: str


@dataclass(frozen=True)
class DpoExample:
    prompt: str
    chosen: str
    rejected: str


@dataclass(frozen=True)
class LoraTrainingConfig:
    base_model: str
    output_dir: str
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    num_train_epochs: int = 3
    learning_rate: float = 2e-4
    per_device_train_batch_size: int = 2


@dataclass(frozen=True)
class LoraTrainingResult:
    adapter_dir: str
    sample_count: int
    final_loss: Optional[float]


def sft_examples_from_pairs(pairs: List[PreferencePair]) -> List[SftExample]:
    """Bir çiftin yalnızca kabul edilen tarafı bir SFT hedefidir -- bir
    çiftin neden tek kanatlı olduğu için `PreferencePair`'ın docstring'ine
    bakın (yalnızca reddedilen bir satırda taklit edilmeye değer bir
    completion yoktur)."""
    return [
        SftExample(prompt=pair.prompt_context, completion=pair.chosen)
        for pair in pairs
        if pair.chosen
    ]


def dpo_examples_from_pairs(pairs: List[PreferencePair]) -> List[DpoExample]:
    """DPO bir çiftin *her iki* tarafına da ihtiyaç duyar -- bugün derlenen
    tek kaynak (explicit_feedback, Aşama 2) yapısı gereği tek kanatlıdır,
    bu yüzden ikinci, gerçekten çiftlenmiş bir sinyal kaynağı (planın HITL
    reject->accept zinciri, hâlâ ertelenmiş -- bkz. `TrainingSampleModel`'in
    docstring'i) onunla birlikte derlenene kadar bu genelde boştur."""
    return [
        DpoExample(prompt=pair.prompt_context, chosen=pair.chosen, rejected=pair.rejected)
        for pair in pairs
        if pair.chosen and pair.rejected
    ]


def export_sft_jsonl(examples: List[SftExample], path: str) -> int:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(
                json.dumps(
                    {"prompt": example.prompt, "completion": example.completion},
                    ensure_ascii=False,
                )
                + "\n"
            )
    return len(examples)


def export_dpo_jsonl(examples: List[DpoExample], path: str) -> int:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(
                json.dumps(
                    {
                        "prompt": example.prompt,
                        "chosen": example.chosen,
                        "rejected": example.rejected,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return len(examples)


def _lora_config(config: LoraTrainingConfig) -> "LoraConfig":
    return LoraConfig(
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        lora_dropout=config.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
    )


def train_lora_sft(sft_jsonl_path: str, config: LoraTrainingConfig) -> LoraTrainingResult:
    """`chosen` completion'ları üzerinde yepyeni bir LoRA adaptörünü
    supervised fine-tune eder.

    Raises:
        RuntimeError: Training worker'ın kendi ML bağımlılıkları bu
            süreçte kurulu değilse (bkz. modül docstring'i).
    """
    _require_training_libs()
    dataset = Dataset.from_json(sft_jsonl_path)

    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base_model = AutoModelForCausalLM.from_pretrained(config.base_model, torch_dtype=_dtype())
    model = get_peft_model(base_model, _lora_config(config))

    dataset = dataset.map(
        lambda example: {"text": f"{example['prompt']}\n{example['completion']}"}
    )

    training_args = SFTConfig(
        output_dir=config.output_dir,
        num_train_epochs=config.num_train_epochs,
        learning_rate=config.learning_rate,
        per_device_train_batch_size=config.per_device_train_batch_size,
        dataset_text_field="text",
        save_strategy="no",
        report_to=[],
    )
    trainer = SFTTrainer(
        model=model, args=training_args, train_dataset=dataset, processing_class=tokenizer
    )
    train_result = trainer.train()

    trainer.model.save_pretrained(config.output_dir)
    tokenizer.save_pretrained(config.output_dir)

    return LoraTrainingResult(
        adapter_dir=config.output_dir,
        sample_count=len(dataset),
        final_loss=getattr(train_result, "training_loss", None),
    )


def train_lora_dpo(
    dpo_jsonl_path: str,
    config: LoraTrainingConfig,
    *,
    sft_adapter_dir: Optional[str] = None,
) -> LoraTrainingResult:
    """`chosen`/`rejected` çiftleri üzerinde bir LoRA adaptörünü tercih
    (preference) optimizasyonundan geçirir.

    `sft_adapter_dir` verilirse, DPO eğitime zaten SFT'lenmiş o adaptörün
    *üzerine* devam eder (planın iki aşamalı `lora_sft` sonra `lora_dpo`
    pipeline'ı); aksi halde base model'den doğrudan yepyeni bir adaptörle
    başlar.

    Raises:
        RuntimeError: Bkz. `train_lora_sft`.
    """
    _require_training_libs()
    dataset = Dataset.from_json(dpo_jsonl_path)

    tokenizer = AutoTokenizer.from_pretrained(config.base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    base_model = AutoModelForCausalLM.from_pretrained(config.base_model, torch_dtype=_dtype())
    if sft_adapter_dir:
        model = PeftModel.from_pretrained(base_model, sft_adapter_dir, is_trainable=True)
    else:
        model = get_peft_model(base_model, _lora_config(config))

    training_args = DPOConfig(
        output_dir=config.output_dir,
        num_train_epochs=config.num_train_epochs,
        learning_rate=config.learning_rate,
        per_device_train_batch_size=config.per_device_train_batch_size,
        save_strategy="no",
        report_to=[],
    )
    trainer = DPOTrainer(
        model=model, args=training_args, train_dataset=dataset, processing_class=tokenizer
    )
    train_result = trainer.train()

    trainer.model.save_pretrained(config.output_dir)
    tokenizer.save_pretrained(config.output_dir)

    return LoraTrainingResult(
        adapter_dir=config.output_dir,
        sample_count=len(dataset),
        final_loss=getattr(train_result, "training_loss", None),
    )


def write_ollama_modelfile(adapter_dir: str, base_model: str, output_path: str) -> str:
    """`FROM {base_model}` + `ADAPTER {adapter_dir}` -- adaptörü çalıştırılabilir
    bir Ollama modeli olarak yayımlamak için `ollama create
    kachow-{slug}:v{n} -f {output_path}`'in ihtiyaç duyduğu iki satır."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(f"FROM {base_model}\nADAPTER {adapter_dir}\n", encoding="utf-8")
    return output_path
