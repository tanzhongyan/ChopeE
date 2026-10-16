# Copy-only arm64 image: no RUN steps, so it builds on an x86 host without QEMU.
# Run services/build_image.sh catalog_cart first (installs aarch64 wheels into build/catalog_cart/deps).
# Build context = repo root.
ARG BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
FROM ${BASE_IMAGE}
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/shared/python:/app/deps UVICORN_WORKERS=1
WORKDIR /app
COPY build/catalog_cart/deps /app/deps
COPY shared/python/chopee shared/python/chopee
COPY services/__init__.py services/__init__.py
COPY services/catalog_cart services/catalog_cart
EXPOSE 8080
# 2 Uvicorn workers per vCPU; Terraform sets UVICORN_WORKERS
CMD ["sh", "-c", "exec python -m uvicorn services.catalog_cart.app:build_app --factory --host 0.0.0.0 --port 8080 --workers ${UVICORN_WORKERS:-1}"]
