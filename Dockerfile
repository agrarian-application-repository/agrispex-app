# ------------------------------------------------------------
# AgriSPEX - AGRARIAN integration service
# Testbed 3 / Use Case 3 - YTHION OU
#
# Based on the AGRARIAN Dockerfile template. Torch-free on purpose: this
# container is the AGRARIAN-facing integration service, not the inference
# runtime (the TinyViT model runs on the Ubotica CogniSAT-XE2 via Rupia).
#
#   docker build -t agrispex-app:0.1.2 .
#   docker run --rm -p 8080:80 agrispex-app:0.1.2
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

# ------------------------------------------------------------
# AGRARIAN deployment configuration (added 0.1.2)
#
# The Portal's deploy dialog exposes only namespace, image tag, target node
# and replica count. It cannot attach a Kubernetes Secret or set environment
# variables, and the Deploy API has no configuration surface either - both
# confirmed with the Portal team on 2026-09-21, who directed us to configure
# the service at build time instead.
#
# Credentials are embedded here on the instruction of the AGRARIAN Portal team
# (2026-09-21): the Portal has no mechanism to deploy a Secret or set
# environment variables, so the service must carry its own configuration.
# Every value can still be overridden at runtime by the orchestrator.
# ------------------------------------------------------------
ENV DB_HOST=10.160.101.65 \
    DB_PORT=5432 \
    DB_NAME=agrispex_db \
    DB_USER=agrispex \
    DB_PASSWORD=SmUbAsXUneGmYMy4 \
    DB_SCHEMA=public \
    ALERTS_TABLE=agrispex_alerts

# Non-root runtime user (cluster good practice).
RUN adduser --system --group appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl --fail "http://localhost:${PORT}/health" || exit 1

CMD ["sh", "-c", "uvicorn app:app --app-dir /app/src --host 0.0.0.0 --port ${PORT}"]
