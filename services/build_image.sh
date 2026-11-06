#!/usr/bin/env bash
# Usage: services/build_image.sh <catalog_cart|checkout> [tag] [--base IMAGE]
# Builds a linux/arm64 image without QEMU: aarch64 wheels are installed on the host, the Dockerfile only COPYs.
set -euo pipefail
svc="${1:?service name: catalog_cart or checkout}"
tag="${2:-chopee-${svc//_/-}:latest}"
build_args=(buildx build --platform linux/arm64)
if [[ "${3:-}" == "--base" ]]; then build_args+=(--build-arg "BASE_IMAGE=${4:?image}"); fi
root="$(cd "$(dirname "$0")/.." && pwd)"
deps="$root/build/$svc/deps"
pip_cmd=("${PYTHON:-python3}" -m pip)
[ -z "${PIP:-}" ] || pip_cmd=("$PIP")
rm -rf "$deps" && mkdir -p "$deps"
"${pip_cmd[@]}" install --quiet --no-cache-dir --target "$deps" --only-binary=:all: \
  --platform manylinux2014_aarch64 --platform manylinux_2_28_aarch64 --platform manylinux_2_17_aarch64 \
  --python-version 3.12 --implementation cp -r "$root/services/$svc/requirements.txt"
docker "${build_args[@]}" -f "$root/services/$svc/Dockerfile" -t "$tag" --load "$root"
