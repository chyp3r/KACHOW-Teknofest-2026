FROM python:3.12-slim

WORKDIR /workspace

# Install system dependencies
# default-jre-headless: required by opendataloader-pdf (Java 11+ CLI)
# tesseract-ocr + tesseract-ocr-tur: Turkish OCR for scanned evrak
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    default-jre-headless \
    tesseract-ocr \
    tesseract-ocr-tur \
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

# Set Python Path
ENV PYTHONPATH=/workspace

# Expose API port
EXPOSE 8000

# Run uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
