"""Unit tests for app.ai.training.lora (Faz C3 Aşama 3, #191).

The pure export/conversion functions are tested for real. `train_lora_sft`/
`train_lora_dpo` cannot be exercised against real torch/transformers/peft/
trl in this test image (they only ship in the training worker's own image,
requirements-training.txt) -- their own RuntimeError-when-unavailable
guard is tested directly (a real, useful assertion given these libraries
are genuinely absent here), and their orchestration is tested by
monkeypatching the module's lazily-imported names to fakes.
"""

from unittest.mock import MagicMock

import pytest

from app.ai.training import lora
from app.ai.training.dataset import PreferencePair


def _pair(chosen=None, rejected=None, index=0) -> PreferencePair:
    return PreferencePair(
        source="explicit_feedback",
        source_feedback_id=f"fb-{index}",
        source_draft_id=None,
        prompt_context=f"context-{index}",
        chosen=chosen,
        rejected=rejected,
        weight=1.0,
        pair_hash=f"hash-{index}",
    )


# ==========================================
# sft_examples_from_pairs / dpo_examples_from_pairs
# ==========================================
def test_sft_examples_only_come_from_chosen_only_pairs():
    pairs = [_pair(chosen="Sayın Makam,", index=0), _pair(rejected="selam", index=1)]

    examples = lora.sft_examples_from_pairs(pairs)

    assert len(examples) == 1
    assert examples[0].prompt == "context-0"
    assert examples[0].completion == "Sayın Makam,"


def test_dpo_examples_require_both_sides_of_a_pair():
    """A single-wing sample (the only kind explicit_feedback ever produces
    today, see PreferencePair's docstring) has no rejected/chosen
    counterpart and cannot become a DPO example."""
    pairs = [
        _pair(chosen="Sayın Makam,", index=0),
        _pair(rejected="selam", index=1),
        _pair(chosen="A", rejected="B", index=2),
    ]

    examples = lora.dpo_examples_from_pairs(pairs)

    assert len(examples) == 1
    assert examples[0] == lora.DpoExample(prompt="context-2", chosen="A", rejected="B")


# ==========================================
# export_sft_jsonl / export_dpo_jsonl
# ==========================================
def test_export_sft_jsonl_writes_one_line_per_example(tmp_path):
    examples = [lora.SftExample(prompt="p1", completion="c1"), lora.SftExample(prompt="p2", completion="c2")]
    path = str(tmp_path / "sub" / "sft.jsonl")

    count = lora.export_sft_jsonl(examples, path)

    assert count == 2
    lines = open(path, encoding="utf-8").read().strip().split("\n")
    assert len(lines) == 2
    assert '"prompt": "p1"' in lines[0]
    assert '"completion": "c1"' in lines[0]


def test_export_dpo_jsonl_writes_chosen_and_rejected(tmp_path):
    examples = [lora.DpoExample(prompt="p", chosen="A", rejected="B")]
    path = str(tmp_path / "dpo.jsonl")

    count = lora.export_dpo_jsonl(examples, path)

    assert count == 1
    content = open(path, encoding="utf-8").read()
    assert '"chosen": "A"' in content
    assert '"rejected": "B"' in content


def test_export_creates_parent_directories(tmp_path):
    path = str(tmp_path / "a" / "b" / "c" / "sft.jsonl")

    lora.export_sft_jsonl([lora.SftExample(prompt="p", completion="c")], path)

    import os

    assert os.path.exists(path)


# ==========================================
# write_ollama_modelfile
# ==========================================
def test_write_ollama_modelfile_content(tmp_path):
    path = str(tmp_path / "Modelfile")

    result_path = lora.write_ollama_modelfile("/artifacts/adapter", "qwen3.5:9b", path)

    assert result_path == path
    content = open(path, encoding="utf-8").read()
    assert content == "FROM qwen3.5:9b\nADAPTER /artifacts/adapter\n"


# ==========================================
# train_lora_sft / train_lora_dpo -- unavailable-libs guard
# ==========================================
def test_train_lora_sft_raises_clearly_when_training_libs_are_absent():
    """The natural, honest state of this test image: peft/trl/transformers
    are not installed here (only in the training worker's own image, see
    requirements-training.txt) -- calling the real training function must
    fail loudly, not silently no-op or crash with an AttributeError/
    ImportError deep in some other module."""
    if lora._TRAINING_LIBS_AVAILABLE:
        pytest.skip("Training libs are installed in this environment.")

    with pytest.raises(RuntimeError, match="LoRA eğitim kütüphaneleri"):
        lora.train_lora_sft("unused.jsonl", lora.LoraTrainingConfig(base_model="x", output_dir="y"))


def test_train_lora_dpo_raises_clearly_when_training_libs_are_absent():
    if lora._TRAINING_LIBS_AVAILABLE:
        pytest.skip("Training libs are installed in this environment.")

    with pytest.raises(RuntimeError, match="LoRA eğitim kütüphaneleri"):
        lora.train_lora_dpo("unused.jsonl", lora.LoraTrainingConfig(base_model="x", output_dir="y"))


# ==========================================
# train_lora_sft / train_lora_dpo -- orchestration, libs mocked
# ==========================================
@pytest.fixture
def fake_training_libs(monkeypatch, tmp_path):
    """Stands in for torch/datasets/peft/transformers/trl so the
    orchestration in train_lora_sft/train_lora_dpo can be exercised
    without those packages actually installed."""
    monkeypatch.setattr(lora, "_TRAINING_LIBS_AVAILABLE", True)

    fake_dataset = MagicMock()
    fake_dataset.map.return_value = fake_dataset
    fake_dataset.__len__.return_value = 3
    fake_dataset_cls = MagicMock()
    fake_dataset_cls.from_json.return_value = fake_dataset
    monkeypatch.setattr(lora, "Dataset", fake_dataset_cls)

    fake_tokenizer = MagicMock(pad_token=None, eos_token="<eos>")
    monkeypatch.setattr(lora, "AutoTokenizer", MagicMock(from_pretrained=MagicMock(return_value=fake_tokenizer)))

    fake_base_model = MagicMock()
    monkeypatch.setattr(
        lora, "AutoModelForCausalLM", MagicMock(from_pretrained=MagicMock(return_value=fake_base_model))
    )

    fake_peft_model = MagicMock()
    monkeypatch.setattr(lora, "get_peft_model", MagicMock(return_value=fake_peft_model))
    monkeypatch.setattr(lora, "LoraConfig", MagicMock())
    monkeypatch.setattr(lora, "PeftModel", MagicMock(from_pretrained=MagicMock(return_value=fake_peft_model)))

    fake_trainer = MagicMock()
    fake_trainer.train.return_value = MagicMock(training_loss=0.42)
    fake_trainer.model = fake_peft_model
    monkeypatch.setattr(lora, "SFTTrainer", MagicMock(return_value=fake_trainer))
    monkeypatch.setattr(lora, "SFTConfig", MagicMock())
    monkeypatch.setattr(lora, "DPOTrainer", MagicMock(return_value=fake_trainer))
    monkeypatch.setattr(lora, "DPOConfig", MagicMock())

    fake_torch = MagicMock()
    fake_torch.cuda.is_available.return_value = False
    fake_torch.float32 = "float32"
    monkeypatch.setattr(lora, "torch", fake_torch)

    return {"trainer": fake_trainer, "peft_model": fake_peft_model, "tokenizer": fake_tokenizer}


def test_train_lora_sft_saves_the_adapter_and_returns_the_result(fake_training_libs, tmp_path):
    config = lora.LoraTrainingConfig(base_model="qwen3.5:9b", output_dir=str(tmp_path / "out"))

    result = lora.train_lora_sft(str(tmp_path / "sft.jsonl"), config)

    assert result.adapter_dir == config.output_dir
    assert result.sample_count == 3
    assert result.final_loss == 0.42
    fake_training_libs["trainer"].train.assert_called_once()
    fake_training_libs["peft_model"].save_pretrained.assert_called_once_with(config.output_dir)
    fake_training_libs["tokenizer"].save_pretrained.assert_called_once_with(config.output_dir)


def test_train_lora_dpo_continues_from_an_sft_adapter_when_given_one(fake_training_libs, tmp_path):
    config = lora.LoraTrainingConfig(base_model="qwen3.5:9b", output_dir=str(tmp_path / "out"))

    lora.train_lora_dpo(str(tmp_path / "dpo.jsonl"), config, sft_adapter_dir="/artifacts/sft-adapter")

    lora.PeftModel.from_pretrained.assert_called_once()
    call_args = lora.PeftModel.from_pretrained.call_args
    assert call_args.args[1] == "/artifacts/sft-adapter"
    assert call_args.kwargs.get("is_trainable") is True
    lora.get_peft_model.assert_not_called()


def test_train_lora_dpo_starts_a_fresh_adapter_without_an_sft_stage(fake_training_libs, tmp_path):
    config = lora.LoraTrainingConfig(base_model="qwen3.5:9b", output_dir=str(tmp_path / "out"))

    lora.train_lora_dpo(str(tmp_path / "dpo.jsonl"), config)

    lora.get_peft_model.assert_called_once()
    lora.PeftModel.from_pretrained.assert_not_called()
