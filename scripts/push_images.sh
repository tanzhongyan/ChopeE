#!/usr/bin/env bash
# Build both services for linux/arm64 and push them to ECR (plan 06 Section 6.4 step 3).
# Usage: scripts/push_images.sh <image_tag> [--dry-run]
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
  run docker buildx build --platform linux/arm64 \
    -f "$ROOT/services/$dir/Dockerfile" -t "$REGISTRY/chopee-$svc:$TAG" --push "$ROOT"
done
echo "pushed ${SERVICES[*]} as :$TAG"
