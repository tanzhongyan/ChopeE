#!/usr/bin/env bash
# Stop one running checkout task mid-burst and verify ECS replaces it while the
# ALB keeps serving (plan 07 failure step). A successful stop-task call alone is
# not success: this script waits for desired/running counts to recover, a new
# task to appear and the old task to reach STOPPED.
#
# Usage: scripts/stop_checkout_task.sh [--cluster NAME] [--service NAME]
#        [--region REGION] [--timeout SECONDS] [--poll SECONDS]
# Defaults: cluster chopee, service chopee-checkout, region ap-southeast-1,
# timeout 300, poll 5. Use --timeout 0 only for a deliberate failure drill.
set -euo pipefail

REGION=${AWS_REGION:-ap-southeast-1}
CLUSTER=chopee
SERVICE=chopee-checkout
TIMEOUT=300
POLL=5

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --cluster) CLUSTER=${2:?--cluster needs a value}; shift 2 ;;
    --service) SERVICE=${2:?--service needs a value}; shift 2 ;;
    --region) REGION=${2:?--region needs a value}; shift 2 ;;
    --timeout) TIMEOUT=${2:?--timeout needs a value}; shift 2 ;;
    --poll) POLL=${2:?--poll needs a value}; shift 2 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$TIMEOUT" in
  ''|*[!0-9]*) echo "ERROR --timeout must be a non-negative integer" >&2; exit 2 ;;
esac
case "$POLL" in
  ''|*[!0-9]*) echo "ERROR --poll must be a non-negative integer" >&2; exit 2 ;;
esac

aws_r() { aws --region "$REGION" "$@"; }

if ! cluster_arn=$(aws_r ecs list-clusters --query "clusterArns[?ends_with(@, '/$CLUSTER')] | [0]" --output text 2>&1); then
  echo "ERROR cluster lookup failed: $cluster_arn" >&2
  exit 1
fi
if [ -z "$cluster_arn" ] || [ "$cluster_arn" = "None" ]; then
  echo "ERROR cluster not found: $CLUSTER" >&2
  exit 1
fi

if ! service_arn=$(aws_r ecs list-services --cluster "$cluster_arn" \
  --query "serviceArns[?ends_with(@, '/$SERVICE')] | [0]" --output text 2>&1); then
  echo "ERROR service lookup failed: $service_arn" >&2
  exit 1
fi
if [ -z "$service_arn" ] || [ "$service_arn" = "None" ]; then
  echo "ERROR service not found: $SERVICE in $CLUSTER" >&2
  exit 1
fi

if ! task=$(aws_r ecs list-tasks --cluster "$cluster_arn" --service-name "$service_arn" \
  --desired-status RUNNING --query 'taskArns[0]' --output text 2>&1); then
  echo "ERROR task lookup failed: $task" >&2
  exit 1
fi
if [ -z "$task" ] || [ "$task" = "None" ]; then
  echo "ERROR no running task for $SERVICE" >&2
  exit 1
fi

echo "stopping $task at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
if ! aws_r ecs stop-task --cluster "$cluster_arn" --task "$task" \
  --reason "chopee demo: task-failure test" >/dev/null 2>&1; then
  echo "ERROR stop-task failed for $task" >&2
  exit 1
fi

echo "waiting up to ${TIMEOUT}s for a replacement task"
running=0
desired=0
old_status=unknown
deadline=$((SECONDS + TIMEOUT))
while [ "$SECONDS" -lt "$deadline" ]; do
  if ! svc=$(aws_r ecs describe-services --cluster "$cluster_arn" --services "$service_arn" \
    --query 'services[0].[runningCount,desiredCount]' --output text 2>&1); then
    echo "ERROR describe-services failed: $svc" >&2
    exit 1
  fi
  read -r running desired <<< "$svc"

  if ! new_task=$(aws_r ecs list-tasks --cluster "$cluster_arn" --service-name "$service_arn" \
    --desired-status RUNNING --query "taskArns[?@ != '$task'] | [0]" --output text 2>&1); then
    echo "ERROR list-tasks failed: $new_task" >&2
    exit 1
  fi
  if ! old_status=$(aws_r ecs describe-tasks --cluster "$cluster_arn" --tasks "$task" \
    --query 'tasks[0].lastStatus' --output text 2>&1); then
    echo "ERROR describe-tasks failed: $old_status" >&2
    exit 1
  fi

  if [ "$running" -ge "$desired" ] && [ -n "$new_task" ] && [ "$new_task" != "None" ] \
    && [ "$old_status" = "STOPPED" ]; then
    echo "PASS: $SERVICE recovered with $new_task (running $running / desired $desired, old task STOPPED)"
    exit 0
  fi
  sleep "$POLL"
done

echo "FAIL: replacement not confirmed within ${TIMEOUT}s (last running=$running desired=$desired old=$old_status)" >&2
exit 1
