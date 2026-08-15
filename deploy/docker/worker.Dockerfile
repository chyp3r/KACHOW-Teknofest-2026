FROM python:3.12-slim

WORKDIR /workspace

# Only the system deps arq/torch/transformers/peft/trl actually need --
# no OCR/Java/Playwright toolchain (backend.Dockerfile's own large layers),
# this image is purely a training worker, never serves the API.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# requirements-training.txt itself does `-r requirements.txt`, so this one
# COPY + install pulls in both.
COPY backend/requirements.txt backend/requirements-training.txt ./

# Real GPU training needs a CUDA-capable torch build matching the host's
# driver -- pip's default resolution here is the CPU wheel, which lets this
# image build and run its own unit tests (mocked ML calls, see
# tests/unit/ai/test_lora.py) anywhere. Swap in an index-url/extra wheel
# for the target GPU host at deploy time (see compose.yml's `worker`
# service comment) rather than baking one CUDA version into this Dockerfile.
RUN pip install --no-cache-dir -r requirements-training.txt

# Only app/ai and app/domains/training + their shared dependencies
# (app/core, app/infrastructure) are actually reachable from
# app.workers.queue's import graph, but copying the whole app/ keeps this
# Dockerfile from having to track that graph by hand as it grows -- same
# tradeoff backend.Dockerfile already makes for its own COPY.
COPY backend/app /workspace/app
COPY backend/tests /workspace/tests
COPY backend/pyproject.toml /workspace/

ENV PYTHONPATH=/workspace

CMD ["arq", "app.workers.queue.WorkerSettings"]
