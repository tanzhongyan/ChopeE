#!/usr/bin/env bash
# Stop one running checkout task mid-burst (plan 07 failure step): ECS replaces it, the ALB keeps serving.
# Usage: scripts/stop_checkout_task.sh   (env: AWS_REGION, default ap-southeast-1)
set -euo pipefail
REGION=${AWS_REGION:-ap-southeast-1}
CLUSTER=$(aws ecs list-clusters --region "$REGION" --query "clusterArns[?contains(@, 'chopee')]|[0]" --output text)
[ -n "$CLUSTER" ] && [ "$CLUSTER" != "None" ] || { echo "no chopee cluster found" >&2; exit 1; }
SERVICE=$(aws ecs list-services --cluster "$CLUSTER" --region "$REGION" --query "serviceArns[?contains(@, 'checkout')]|[0]" --output text)
TASK=$(aws ecs list-tasks --cluster "$CLUSTER" --service-name "$SERVICE" --desired-status RUNNING --region "$REGION" --query 'taskArns[0]' --output text)
[ -n "$TASK" ] && [ "$TASK" != "None" ] || { echo "no running checkout task" >&2; exit 1; }
echo "stopping $TASK"
aws ecs stop-task --cluster "$CLUSTER" --task "$TASK" --reason "chopee demo: task-failure test" --region "$REGION" >/dev/null
echo "watch: aws ecs describe-services --cluster $CLUSTER --services $SERVICE --region $REGION --query 'services[0].events[:5]'"
