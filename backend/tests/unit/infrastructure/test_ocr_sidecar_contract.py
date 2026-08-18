"""Contract test between OllamaVisionExtractor and scripts/ocr_sidecar.py.

scripts/ocr_sidecar.py serves a Hugging Face transformers model from the host
(Docker on macOS has no Metal passthrough -- see the plan in
.claude/plans/you-are-an-expert-silly-puzzle.md) by mimicking Ollama's own
`/api/generate` HTTP contract, so `OllamaVisionExtractor` can point at it with
no code changes. That claim is only worth anything if it is exercised through
the real client code -- `OllamaVisionExtractor._transcribe` -- rather than a
hand-copied payload dict that could silently drift from the real one. This
spins up the sidecar's actual `ThreadingHTTPServer` with a fake, instant
backend (no model weights, no torch needed here) on a free port, then drives
it with the real extractor exactly as production would.
"""

import base64
import os
import sys
import threading

import pytest

from app.infrastructure.extractors.vision import DEFAULT_PROMPT, OllamaVisionExtractor

_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts")
sys.path.insert(0, os.path.abspath(_SCRIPTS_DIR))
import ocr_sidecar  # noqa: E402


class _FakeBackend(ocr_sidecar.Backend):
    """Stands in for a real transformers model -- returns instantly so this
    test costs milliseconds, not a multi-GB model download."""

    def __init__(self, model_id: str, reply: str) -> None:
        super().__init__(model_id, device="cpu", dtype=None)
        self.reply = reply
        self.last_prompt = None
        self.last_image_bytes = None

    def load(self) -> None:
        self.loaded = True

    def generate(self, image_bytes: bytes, prompt: str, max_new_tokens: int) -> str:
        self.last_prompt = prompt
        self.last_image_bytes = image_bytes
        return self.reply


@pytest.fixture
def sidecar_server():
    """Start ocr_sidecar's real HTTP server on an OS-assigned free port."""
    backend = _FakeBackend("fake/contract-model", reply="MERKEZ VALİLİĞİNE")
    lock = threading.Lock()
    server = ocr_sidecar.ThreadingHTTPServer(
        ("127.0.0.1", 0), ocr_sidecar._make_handler(backend, lock)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, backend
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_ollama_vision_extractor_works_unmodified_against_the_sidecar(sidecar_server):
    """The whole point of the sidecar: OllamaVisionExtractor needs zero code
    changes, only a different base_url, to use a transformers model served
    this way instead of a real Ollama instance."""
    server, backend = sidecar_server
    port = server.server_address[1]

    extractor = OllamaVisionExtractor(
        model=backend.model_id, base_url=f"http://127.0.0.1:{port}"
    )
    # A 1x1 PNG -- the sidecar contract only cares that bytes flow through
    # correctly, not that the image is a real scanned page.
    tiny_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

    result = await extractor.extract(tiny_png, file_name="page.png", mime_type="image/png")

    assert result.text == "MERKEZ VALİLİĞİNE"
    assert result.used_ocr is True
    assert result.extractor == "ollama_vision"
    # Confirms the real payload shape reached the sidecar: prompt text and
    # raw image bytes both survived the base64 round-trip through the real
    # client code, not a test-only shortcut.
    assert backend.last_prompt == DEFAULT_PROMPT
    assert backend.last_image_bytes == tiny_png
