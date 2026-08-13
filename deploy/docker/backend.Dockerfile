FROM python:3.12-slim

WORKDIR /workspace

# Install system dependencies
# default-jre-headless: required by opendataloader-pdf (Java 11+ CLI)
# tesseract-ocr + tesseract-ocr-tur: Turkish OCR for scanned evrak
# antiword: deterministic text extraction for the legacy binary .doc corpus
# git: needed below to pip-install mevzuat-mcp straight from its GitHub
#   source -- it has no PyPI release with the search_mevzuat/get_mevzuat_content
#   pair this project's legislation lookup needs (see
#   scripts/fetch_mevzuat_corpus.py's docstring)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    default-jre-headless \
    tesseract-ocr \
    tesseract-ocr-tur \
    antiword \
    git \
    && rm -rf /var/lib/apt/lists/*

# mevzuat-mcp (github.com/saidsurucu/mevzuat-mcp, MIT) backs both live
# legislation retrieval for document analysis (MEVZUAT_SOURCE=mcp, the
# default -- see app/ai/retrieval/mcp_mevzuat.py) and the assistant's live
# lookup tool (MEVZUAT_MCP_ENABLED). Installed into its own venv, not
# alongside this project's own requirements: its dependency tree resolves
# fastapi/pydantic/httpx/mcp to versions close enough to this project's own
# pins to look safe at a glance, but not identical (pydantic-settings
# 2.15.0 here vs requirements.txt's 2.14.2), and requirements.txt's exact
# pins are not worth risking for the sake of skipping one `python -m venv`.
#
# `playwright install --with-deps` is what makes this layer large -- it
# downloads a full headless Chromium (git+mevzuat-mcp's own dependency,
# used to query mevzuat.gov.tr) and the ~20 system libraries it needs to
# run, a few hundred MB together. It shells out to apt-get itself, which is
# why the apt cache is cleaned only after this step, not before it.
RUN python -m venv /tmp/mcpvenv \
    && /tmp/mcpvenv/bin/pip install --no-cache-dir --upgrade pip \
    && /tmp/mcpvenv/bin/pip install --no-cache-dir "git+https://github.com/saidsurucu/mevzuat-mcp" \
    && /tmp/mcpvenv/bin/playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements. -dev pulls in requirements.txt too, plus
# pytest-cov/pytest-timeout and the langgraph-checkpoint memory saver the test
# suite's HITL integration test uses -- installing only requirements.txt (the
# previous behaviour) left those absent from the image entirely.
COPY backend/requirements.txt backend/requirements-dev.txt ./

# Install Python requirements
RUN pip install --no-cache-dir -r requirements-dev.txt

# Copy backend application code
COPY backend/app /workspace/app
COPY backend/tests /workspace/tests
COPY backend/alembic /workspace/alembic
COPY backend/alembic.ini backend/pyproject.toml /workspace/

# Copy the legislation corpus; without it the BM25 half of the hybrid retriever
# is empty and mevzuat suggestions silently degrade.
COPY datasets /workspace/datasets

# Copy the evaluation harness. tests/unit/evaluation/ imports `evaluation.*`,
# so this has to be in the image for the test suite to collect at all -- not
# just mounted for `make eval`.
COPY evaluation /workspace/evaluation

# Set Python Path
ENV PYTHONPATH=/workspace

# Expose API port
EXPOSE 8000

# Run uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
