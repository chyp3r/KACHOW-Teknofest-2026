# Production image. deploy/docker/backend.Dockerfile (dev) stays a single
# stage that bakes in the test suite, evaluation/, and build tooling because
# `docker compose run backend pytest ...` needs all of that inside the
# container. None of it belongs on the critical path of a request -- this
# file trims it down to runtime-only and non-root.

# ---------------------------------------------------------------------------
# Stage 1: builder -- compile the Python dependency wheels/venv. Only
# requirements.txt, never requirements-dev.txt (pytest, pytest-benchmark,
# Levenshtein -- none of it runs in production). reportlab moved into
# requirements.txt: the draft docx/pdf export endpoint is a prod feature.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: mcp -- mevzuat-mcp's own venv plus a full headless Chromium (its
# own transitive dependency, used to query mevzuat.gov.tr live). ARG
# WITH_MEVZUAT_MCP=1 by default: LOCAL_MODE=false (configmap.yaml's own
# documented default) uses live mevzuat-mcp at every stage -- chat, evrak
# analizi, taslak -- so a fresh build needs it present, not opted into.
# Chromium + the ~20 system libraries `playwright install --with-deps`
# pulls in are a few hundred MB (see docs/deployment/configuration.md for
# the measured delta); operators who genuinely never need live legislation
# (LOCAL_MODE stays "true", MEVZUAT_SOURCE=local) can skip the weight with
# `--build-arg WITH_MEVZUAT_MCP=0` -- the boot-time curated-legislation
# warm-up and the committed corpus (datasets/mevzuat_corpus/) both keep
# working without this stage either way.
FROM python:3.12-slim AS mcp
ARG WITH_MEVZUAT_MCP=1

RUN if [ "$WITH_MEVZUAT_MCP" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends git \
        && python -m venv /tmp/mcpvenv \
        && /tmp/mcpvenv/bin/pip install --no-cache-dir --upgrade pip \
        && /tmp/mcpvenv/bin/pip install --no-cache-dir "git+https://github.com/saidsurucu/mevzuat-mcp" \
        && /tmp/mcpvenv/bin/playwright install --with-deps chromium \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        mkdir -p /tmp/mcpvenv; \
    fi

# ---------------------------------------------------------------------------
# Stage 3: runtime -- only what a running process needs. No build-essential,
# no git, no libpq-dev (libpq5 is the runtime counterpart), no test suite, no
# evaluation/ (tests/unit/evaluation/ imports evaluation.*, so leaving it out
# is also what guarantees this image cannot run that suite -- deliberate).
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /workspace

# default-jre-headless: opendataloader-pdf (Java 11+ CLI).
# tesseract-ocr + tesseract-ocr-tur: Turkish OCR for scanned evrak.
# antiword: deterministic text extraction for the legacy binary .doc corpus.
# fonts-liberation: Times New Roman-metric serif with full Turkish glyphs,
#   used by the draft PDF export (app.domains.drafts.export).
# libpq5: asyncpg/psycopg runtime client library (not -dev; no compilation
# happens in this stage).
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    tesseract-ocr \
    tesseract-ocr-tur \
    antiword \
    fonts-liberation \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=mcp /tmp/mcpvenv /tmp/mcpvenv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/app /workspace/app
COPY backend/alembic /workspace/alembic
COPY backend/alembic.ini /workspace/alembic.ini

# The legislation corpus; without it the BM25 half of the hybrid retriever is
# empty and mevzuat suggestions silently degrade. Needed regardless of
# WITH_MEVZUAT_MCP -- it's also the MEVZUAT_SOURCE=local fallback's source.
COPY datasets /workspace/datasets

ENV PYTHONPATH=/workspace

# GID 0 rather than a dedicated group: OpenShift-style deployments assign a
# random, arbitrary UID at runtime but always keep it in group 0, so a
# hardcoded UID-based ownership would break there. chown'd here rather than
# left to a k8s initContainer -- the directory must exist and be writable
# from the first container start, including a plain `docker run`.
RUN useradd -u 10001 -r -g 0 kachow \
    && mkdir -p /workspace/storage_data \
    && chown -R 10001:0 /workspace/storage_data
USER 10001

EXPOSE 8000

# No curl in python:3.12-slim; urllib is stdlib and needs no extra layer.
# Shallow health, not ?deep=true -- a transient Qdrant/Ollama outage should
# not restart an otherwise-healthy process. Deep checks belong to a
# Kubernetes readiness probe, not this container-level healthcheck.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
