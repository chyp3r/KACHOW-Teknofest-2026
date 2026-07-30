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

# Copy Python requirements
COPY backend/requirements.txt .

# Install Python requirements
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY backend/app /workspace/app

# Copy the legislation corpus; without it the BM25 half of the hybrid retriever
# is empty and mevzuat suggestions silently degrade.
COPY datasets /workspace/datasets

# Set Python Path
ENV PYTHONPATH=/workspace

# Expose API port
EXPOSE 8000

# Run uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
