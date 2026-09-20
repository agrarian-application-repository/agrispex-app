# ------------------------------------------------------------
# AgriSPEX - AGRARIAN integration service
# Testbed 3 / Use Case 3 - YTHION OU
#
# Based on the AGRARIAN Dockerfile template. Torch-free on purpose: this
# container is the AGRARIAN-facing integration service, not the inference
# runtime (the TinyViT model runs on the Ubotica CogniSAT-XE2 via Rupia).
#
#   docker build -t agrispex-app:0.1.1 .
#   docker run --rm -p 8080:80 --env-file .env agrispex-app:0.1.1
# ------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=80 \
    PYTHONPATH=/app/src

WORKDIR /app

# curl is required by the HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Non-root runtime user (cluster good practice).
RUN adduser --system --group appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl --fail "http://localhost:${PORT}/health" || exit 1

CMD ["sh", "-c", "uvicorn app:app --app-dir /app/src --host 0.0.0.0 --port ${PORT}"]
