#!/usr/bin/env bash
# Build both services for linux/arm64 and push them to ECR (plan 06 Section 6.4 step 3).
# Usage: scripts/push_images.sh <image_tag> [--dry-run]
# Optional env BASE_IMAGE overrides the base (e.g. python:3.12-slim if ECR Public rate-limits).
# Needs: docker buildx, aws CLI, ECR repos chopee-catalog-cart and chopee-checkout (module.registry).
set -euo pipefail

usage() { echo "Usage: $0 <image_tag> [--dry-run]   (env: AWS_REGION, default ap-southeast-1)"; }
case "${1:-}" in -h|--help) usage; exit 0 ;; "") usage >&2; exit 2 ;; esac

TAG=$1
DRY=${2:-}
REGION=${AWS_REGION:-ap-southeast-1}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SERVICES=(catalog-cart checkout)

run() { if [ "$DRY" = "--dry-run" ]; then echo "+ $*"; else "$@"; fi; }

if [ "$DRY" = "--dry-run" ]; then
  REGISTRY="<account>.dkr.ecr.${REGION}.amazonaws.com"
else
  ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
  REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
fi

for svc in "${SERVICES[@]}"; do
  dir=${svc//-/_}
  # Dockerfiles only COPY: install the aarch64 wheels on the host first (same as services/build_image.sh).
  run rm -rf "$ROOT/build/$dir/deps"
  run mkdir -p "$ROOT/build/$dir/deps"
  run "${PIP:-pip}" install --quiet --no-cache-dir --target "$ROOT/build/$dir/deps" --only-binary=:all: \
    --platform manylinux2014_aarch64 --platform manylinux_2_28_aarch64 --platform manylinux_2_17_aarch64 \
    --python-version 3.12 --implementation cp -r "$ROOT/services/$dir/requirements.txt"
  run docker buildx build --platform linux/arm64 ${BASE_IMAGE:+--build-arg BASE_IMAGE=$BASE_IMAGE} \
    -f "$ROOT/services/$dir/Dockerfile" -t "$REGISTRY/chopee-$svc:$TAG" --push "$ROOT"
done
echo "pushed ${SERVICES[*]} as :$TAG"
