FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/pyproject.toml .
COPY backend/app ./app
COPY MiniCPM-OCR/sdk/minicpmvocr ./minicpmvocr
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    .
COPY backend/ .
COPY docs/ ./docs/
RUN mkdir -p /data/storage
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
