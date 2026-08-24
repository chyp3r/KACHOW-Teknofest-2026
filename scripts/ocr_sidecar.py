#!/usr/bin/env python3
"""Ollama-compatible OCR sidecar serving one Hugging Face transformers
vision-language model on the host.

Why this exists: Docker on macOS has no Metal passthrough, so a torch model
cannot run at usable speed inside `kachow_backend_dev` (CPU-only aarch64).
The host is where Ollama already runs with Metal, so this serves a
transformers model from there too -- the same "external dependency reached
over host.docker.internal" shape `OLLAMA_BASE_URL` already uses. See
`.claude/plans/you-are-an-expert-silly-puzzle.md` for the full comparison
this was built for.

Implements exactly the subset of Ollama's `/api/generate` contract that
`OllamaVisionExtractor._transcribe()` (backend/app/infrastructure/extractors/
vision.py) calls:

    POST /api/generate
    {"model": ..., "prompt": ..., "images": [<base64 PNG>], "stream": false,
     "options": {"temperature": 0, "num_predict": ..., "num_ctx": ...}}
    -> {"response": "<transcription>"}

Because the contract matches exactly, `OllamaVisionExtractor` needs zero code
changes to use a model served here -- point `base_url` (or
`OLLAMA_VISION_BASE_URL`) at this server's origin and the rest of the
production chain (raster cache, header-band crop, detect_marks, splice) runs
completely unmodified. This is deliberate: it means a benchmark run and a
real production request exercise the identical client-side code path.

One model resident at a time -- 16GB unified memory shared with Docker and
Ollama does not comfortably hold more. Restart with a different --model to
switch. The model loads lazily on the first request, not at startup, so
starting the server costs nothing until it is actually used.

Usage:
    .venv-ocr5/bin/python scripts/ocr_sidecar.py --model zai-org/GLM-OCR
    .venv-ocr5/bin/python scripts/ocr_sidecar.py --model ATH-MaaS/OvisOCR2
    .venv-ocr4/bin/python scripts/ocr_sidecar.py \\
        --model Trendyol/Trendyol-Vision-Flash --family internvl
"""

import argparse
import base64
import io
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 11435
DEFAULT_MAX_NEW_TOKENS = 2048
#: A raw 300 DPI PDF page (e.g. 2496x3507 for A4) is 4-6x more pixels than
#: this on each side. Measured directly on OvisOCR2/CY-012: capping to this
#: size cut generation time ~26% (216.4s -> 161.0s) with no loss of the
#: fields this project's benchmark scores -- the model's own vision tower
#: does not need print-resolution input to read a page of body text.
MAX_IMAGE_DIMENSION = 1280


class Backend:
    """Loads one HF model once and transcribes one image against one prompt.

    Subclasses implement the two model families this project measured --
    see NativeVLBackend and InternVLBackend below for why they need
    different code at all.
    """

    def __init__(self, model_id: str, device: str, dtype) -> None:
        self.model_id = model_id
        self.device = device
        self.dtype = dtype
        self.loaded = False

    def load(self) -> None:
        raise NotImplementedError

    def generate(self, image_bytes: bytes, prompt: str, max_new_tokens: int) -> str:
        raise NotImplementedError


class NativeVLBackend(Backend):
    """zai-org/GLM-OCR, ATH-MaaS/OvisOCR2.

    Both ship a native `AutoModelForImageTextToText` architecture
    (`GlmOcrForConditionalGeneration` / `Qwen3_5ForConditionalGeneration` --
    verified against each model's real `config.json` before writing this,
    not assumed from the model card prose) with a standard chat-template
    processor, so one implementation covers both. No `trust_remote_code`:
    these are first-class transformers model classes, not repo-hosted
    custom code.
    """

    def load(self) -> None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self._torch = torch
        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.model = (
            AutoModelForImageTextToText.from_pretrained(self.model_id, dtype=self.dtype)
            .to(self.device)
            .eval()
        )
        self.loaded = True

    def generate(self, image_bytes: bytes, prompt: str, max_new_tokens: int) -> str:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.device)
        # Only the image tensor needs to match the model's compute dtype --
        # input_ids/attention_mask must stay integral, which .to(device)
        # alone already preserves.
        if "pixel_values" in inputs:
            inputs["pixel_values"] = inputs["pixel_values"].to(self.dtype)

        with self._torch.no_grad():
            generated = self.model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False
            )
        output_ids = generated[0][inputs["input_ids"].shape[1] :]
        return self.processor.decode(output_ids, skip_special_tokens=True).strip()


class InternVLBackend(Backend):
    """Trendyol/Trendyol-Vision-Flash.

    `InternVLChatModel`, requires `trust_remote_code=True`, and is called
    through `model.chat(tokenizer, pixel_values, question, generation_config)`
    rather than a standard `generate()` call -- copied from the model card's
    own quickstart. Deliberately **not** InternVL's usual multi-tile
    `dynamic_preprocess`: this "Flash" variant's card shows only a single
    fixed 448x448 resize (confirmed by reading the raw README source, not a
    paraphrase, to check for a tiling function before assuming one either
    way).
    """

    IMAGENET_MEAN = (0.485, 0.456, 0.406)
    IMAGENET_STD = (0.229, 0.224, 0.225)
    INPUT_SIZE = 448

    def load(self) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, trust_remote_code=True, use_fast=False
        )
        self.model = (
            AutoModel.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                dtype=self.dtype,
                low_cpu_mem_usage=True,
                use_flash_attn=False,
            )
            .to(self.device)
            .eval()
        )
        self.loaded = True

    def _transform(self, image):
        from torchvision import transforms as T
        from torchvision.transforms.functional import InterpolationMode

        pipeline = T.Compose(
            [
                T.Lambda(lambda img: img.convert("RGB") if img.mode != "RGB" else img),
                T.Resize(
                    (self.INPUT_SIZE, self.INPUT_SIZE),
                    interpolation=InterpolationMode.BICUBIC,
                ),
                T.ToTensor(),
                T.Normalize(mean=self.IMAGENET_MEAN, std=self.IMAGENET_STD),
            ]
        )
        return pipeline(image).unsqueeze(0)

    def generate(self, image_bytes: bytes, prompt: str, max_new_tokens: int) -> str:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        pixel_values = self._transform(image).to(self.device, dtype=self.dtype)
        question = f"<image>\n{prompt}"
        generation_config = {"max_new_tokens": max_new_tokens, "do_sample": False}
        with self._torch.no_grad():
            response = self.model.chat(self.tokenizer, pixel_values, question, generation_config)
        return response.strip()


BACKENDS = {"native": NativeVLBackend, "internvl": InternVLBackend}


def _pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _make_handler(backend: Backend, lock: threading.Lock):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args) -> None:  # noqa: A003 - stdlib signature
            sys.stderr.write("[ocr_sidecar] " + (fmt % args) + "\n")

        def _write_json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib signature
            self._write_json(
                200,
                {
                    "status": "ok",
                    "model": backend.model_id,
                    "loaded": backend.loaded,
                    "device": backend.device,
                },
            )

        def do_POST(self) -> None:  # noqa: N802 - stdlib signature
            if self.path != "/api/generate":
                self._write_json(404, {"error": "not found"})
                return

            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._write_json(400, {"error": f"invalid JSON: {exc}"})
                return

            prompt = payload.get("prompt", "")
            images = payload.get("images") or []
            if not images:
                self._write_json(400, {"error": "no images in request"})
                return
            options = payload.get("options") or {}
            max_new_tokens = options.get("num_predict") or DEFAULT_MAX_NEW_TOKENS
            image_bytes = base64.b64decode(images[0])

            # Serialised: one model, one request in flight at a time (see
            # module docstring -- this mirrors Ollama's own behaviour of
            # queuing concurrent generation requests against one model).
            with lock:
                if not backend.loaded:
                    self.log_message("loading %s ...", backend.model_id)
                    started = time.time()
                    try:
                        backend.load()
                    except Exception as exc:  # noqa: BLE001
                        self._write_json(500, {"error": f"model load failed: {exc}"})
                        return
                    self.log_message("loaded in %.1fs", time.time() - started)

                started = time.time()
                try:
                    text = backend.generate(image_bytes, prompt, max_new_tokens)
                except Exception as exc:  # noqa: BLE001 - report, don't crash the server
                    self._write_json(500, {"error": f"generation failed: {exc}"})
                    return
                elapsed = time.time() - started
            self.log_message("generated %d chars in %.1fs", len(text), elapsed)
            self._write_json(200, {"response": text, "done": True})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", required=True, help="Hugging Face model id, e.g. zai-org/GLM-OCR"
    )
    parser.add_argument(
        "--family",
        choices=sorted(BACKENDS),
        default="native",
        help=(
            "native: GLM-OCR/OvisOCR2 (AutoModelForImageTextToText). "
            "internvl: Trendyol-Vision-Flash (trust_remote_code .chat())."
        ),
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--device", default=None, help="Override device (mps/cpu); autodetected otherwise."
    )
    args = parser.parse_args()

    import torch

    device = args.device or _pick_device()
    # float16, not bfloat16: MPS's bfloat16 op coverage is partial and some
    # ops silently fall back to CPU, which would make timing measurements
    # meaningless without any visible error.
    dtype = torch.float16
    print(f"[ocr_sidecar] device={device} dtype={dtype} model={args.model} family={args.family}")

    backend = BACKENDS[args.family](args.model, device, dtype)
    lock = threading.Lock()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _make_handler(backend, lock))
    print(
        f"[ocr_sidecar] listening on http://127.0.0.1:{args.port} "
        "(model loads lazily on first request)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
