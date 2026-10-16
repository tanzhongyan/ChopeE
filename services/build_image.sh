#!/usr/bin/env bash
# Usage: services/build_image.sh <catalog_cart|checkout> [tag] [--base IMAGE]
# Builds a linux/arm64 image without QEMU: aarch64 wheels are installed on the host, the Dockerfile only COPYs.
set -euo pipefail
svc="${1:?service name: catalog_cart or checkout}"
tag="${2:-chopee-${svc//_/-}:latest}"
base_args=()
if [[ "${3:-}" == "--base" ]]; then base_args=(--build-arg "BASE_IMAGE=${4:?image}"); fi
root="$(cd "$(dirname "$0")/.." && pwd)"
deps="$root/build/$svc/deps"
rm -rf "$deps" && mkdir -p "$deps"
pip install --quiet --no-cache-dir --target "$deps" --only-binary=:all: \
  --platform manylinux2014_aarch64 --platform manylinux_2_28_aarch64 --platform manylinux_2_17_aarch64 \
  --python-version 3.12 --implementation cp -r "$root/services/$svc/requirements.txt"
docker buildx build --platform linux/arm64 "${base_args[@]}" -f "$root/services/$svc/Dockerfile" -t "$tag" --load "$root"
