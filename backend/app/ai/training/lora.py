"""LoRA/PEFT fine-tuning -- Faz C3, Aşama 3 (#191).

Lazily imports `torch`/`datasets`/`peft`/`transformers`/`trl`: those only
ship in the training worker's image (`requirements-training.txt`), never
the main backend's. Importing this module (e.g. transitively, since
`app.workers.training` is the only real caller) must never fail just
because those packages are absent from a process that never calls the
functions below -- only actually calling `train_lora_sft`/`train_lora_dpo`
without them installed raises a clear `RuntimeError`. Every name that would
normally come from those imports is still bound (to `None`) when the
import fails, so tests can monkeypatch them without the packages present.

No `app.domains` import here either, same rule `app.ai.training.dataset`
documents: `app.workers.training` resolves `PreferencePair`s from the DB
and hands them in as plain data.
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
    """Only the accepted side of a pair is an SFT target -- see
    `PreferencePair`'s docstring for why a pair is single-wing (a
    rejected-only row has no completion worth imitating)."""
    return [
        SftExample(prompt=pair.prompt_context, completion=pair.chosen)
        for pair in pairs
        if pair.chosen
    ]


def dpo_examples_from_pairs(pairs: List[PreferencePair]) -> List[DpoExample]:
    """DPO needs *both* sides of a pair -- today's only compiled source
    (explicit_feedback, Aşama 2) is single-wing by construction, so this is
    typically empty until a second, genuinely paired signal source (the
    plan's HITL reject->accept chain, still deferred -- see
    `TrainingSampleModel`'s docstring) is compiled alongside it."""
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
    """Supervised fine-tune a fresh LoRA adapter on `chosen` completions.

    Raises:
        RuntimeError: If the training worker's own ML dependencies aren't
            installed in this process (see the module docstring).
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
    """Preference-optimize a LoRA adapter on `chosen`/`rejected` pairs.

    If `sft_adapter_dir` is given, DPO continues training *on top of* that
    already-SFT'd adapter (the plan's two-stage `lora_sft` then `lora_dpo`
    pipeline); otherwise it starts a fresh adapter directly from the base
    model.

    Raises:
        RuntimeError: See `train_lora_sft`.
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
    """`FROM {base_model}` + `ADAPTER {adapter_dir}` -- the two lines
    `ollama create kachow-{slug}:v{n} -f {output_path}` needs to publish
    the adapter as a runnable Ollama model."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(f"FROM {base_model}\nADAPTER {adapter_dir}\n", encoding="utf-8")
    return output_path
