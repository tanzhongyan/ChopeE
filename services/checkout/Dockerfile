# Copy-only arm64 image: no RUN steps, so it builds on an x86 host without QEMU.
# Run services/build_image.sh checkout first (installs aarch64 wheels into build/checkout/deps).
# Build context = repo root.
# python:3.12-slim pinned by multi-arch index digest (resolved 2026-11-03); refresh deliberately.
ARG BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
FROM ${BASE_IMAGE}
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/shared/python:/app/deps UVICORN_WORKERS=2
WORKDIR /app
COPY build/checkout/deps /app/deps
COPY shared/python/chopee shared/python/chopee
COPY services/__init__.py services/__init__.py
COPY services/checkout services/checkout
# Numeric non-root UID (no RUN needed; the app writes nothing to disk).
USER 10001
EXPOSE 8080
# 2 Uvicorn workers per vCPU; Terraform sets UVICORN_WORKERS
CMD ["sh", "-c", "exec python -m uvicorn services.checkout.app:build_app --factory --host 0.0.0.0 --port 8080 --workers ${UVICORN_WORKERS:-2}"]
