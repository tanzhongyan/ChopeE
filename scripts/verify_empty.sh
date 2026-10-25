#!/usr/bin/env bash
# Verify nothing from a ChopeE run is left (plan 04 "Budget and teardown"). Exit 0 only if everything is empty.
# Usage: scripts/verify_empty.sh [--tf-dir DIR]     (env: AWS_REGION, default ap-southeast-1)
# The budget root (infra/budget) is deliberately kept and is not checked.
set -uo pipefail

TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/infra/terraform"
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --tf-dir) TF_DIR=$2; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
REGION=${AWS_REGION:-ap-southeast-1}
FAIL=0

# check <label> <output>: a non-empty output is a leftover.
check() {
  if [ -n "$2" ] && [ "$2" != "None" ]; then echo "LEFTOVER $1:"; echo "$2" | sed 's/^/    /'; FAIL=1; else echo "ok       $1"; fi
}
# query <label> <command...>: an AWS call that errors counts as a failure, not as "empty".
query() {
  local label=$1; shift
  local out
  if ! out=$("$@" 2>&1); then echo "ERROR    $label: $out"; FAIL=1; return; fi
  check "$label" "$out"
}
aws_r() { aws --region "$REGION" "$@"; }

# Scheduler deletes groups asynchronously. Only DELETING groups can resolve by
# waiting; ACTIVE/unknown states and API errors must still fail verification.
# Six polls allow 60 seconds of backoff (2+4+8+16+30), plus API execution time.
check_scheduler_groups() {
  local out attempt=1 delay=2 max_attempts=6
  while :; do
    if ! out=$(aws_r scheduler list-schedule-groups --name-prefix chopee \
      --query 'ScheduleGroups[].[Name,State]' --output text 2>&1); then
      echo "ERROR    scheduler groups: $out"; FAIL=1; return
    fi
    if [ -z "$out" ] || [ "$out" = "None" ]; then
      check "scheduler groups" ""; return
    fi
    if ! printf '%s\n' "$out" | awk 'NF != 2 || $2 != "DELETING" { exit 1 }'; then
      check "scheduler groups" "$out"; return
    fi
    if [ "$attempt" -ge "$max_attempts" ]; then
      echo "ERROR    scheduler groups: deletion wait exhausted after $max_attempts polls"
      check "scheduler groups" "$out"; return
    fi
    echo "WAIT     scheduler groups: DELETING (poll $attempt/$max_attempts; retry in ${delay}s)"
    if ! sleep "$delay"; then
      echo "ERROR    scheduler groups: wait interrupted"; FAIL=1; return
    fi
    attempt=$((attempt + 1))
    delay=$((delay * 2))
    [ "$delay" -le 30 ] || delay=30
  done
}

# 1. Terraform state is empty (or has no state at all).
if [ -d "$TF_DIR" ]; then
  if out=$(terraform -chdir="$TF_DIR" state list 2>&1); then check "terraform state" "$out"
  elif echo "$out" | grep -qi "no state file\|does not have a state"; then echo "ok       terraform state (none)"
  else echo "ERROR    terraform state: $out"; FAIL=1; fi
fi

# Wait before the tag sweep: a deleting group may still be tagged. Never clear
# FAIL here, since Terraform state or other resources may independently remain.
check_scheduler_groups

# 2. Everything tagged Project=chopee, regional and CloudFront (global resources are indexed in us-east-1).
for r in "$REGION" us-east-1; do
  query "tagged resources in $r" aws --region "$r" resourcegroupstaggingapi get-resources \
    --tag-filters Key=Project,Values=chopee --query "ResourceTagMappingList[?!contains(ResourceARN,':budget/chopee-project-cap')].ResourceARN" --output text
done

# 3. Name-scoped checks for untagged leftovers.
query "CloudFront distributions" aws cloudfront list-distributions \
  --query "DistributionList.Items[?contains(Comment || '', 'chopee')].Id" --output text
query "Lambda log groups" aws_r logs describe-log-groups --log-group-name-prefix /aws/lambda/chopee- --query 'logGroups[].logGroupName' --output text
query "ECS log groups" aws_r logs describe-log-groups --log-group-name-prefix /ecs/chopee- --query 'logGroups[].logGroupName' --output text
query "Lambda functions" aws_r lambda list-functions --query "Functions[?starts_with(FunctionName,'chopee-')].FunctionName" --output text
query "Lambda layers" aws_r lambda list-layers --query "Layers[?starts_with(LayerName,'chopee-')].LayerName" --output text
query "ECR repositories" aws_r ecr describe-repositories --query "repositories[?starts_with(repositoryName,'chopee-')].repositoryName" --output text
query "ECS clusters" aws_r ecs list-clusters --query "clusterArns[?contains(@,'chopee-')]" --output text
query "load balancers" aws_r elbv2 describe-load-balancers --query "LoadBalancers[?starts_with(LoadBalancerName,'chopee-')].LoadBalancerArn" --output text
query "target groups" aws_r elbv2 describe-target-groups --query "TargetGroups[?starts_with(TargetGroupName,'chopee-')].TargetGroupArn" --output text
query "VPCs" aws_r ec2 describe-vpcs --filters Name=tag:Project,Values=chopee --query 'Vpcs[].VpcId' --output text
query "security groups" aws_r ec2 describe-security-groups --filters Name=tag:Project,Values=chopee --query 'SecurityGroups[].GroupId' --output text
query "Cognito user pools" aws_r cognito-idp list-user-pools --max-results 60 --query "UserPools[?starts_with(Name,'chopee')].Id" --output text
query "SQS queues" aws_r sqs list-queues --queue-name-prefix chopee- --query 'QueueUrls' --output text
query "SNS topics" aws_r sns list-topics --query "Topics[?contains(TopicArn,':chopee-')].TopicArn" --output text
query "DynamoDB tables" aws_r dynamodb list-tables --query "TableNames[?starts_with(@,'chopee')]" --output text
query "DynamoDB backups" aws_r dynamodb list-backups --query "BackupSummaries[?starts_with(TableName,'chopee')].BackupArn" --output text
query "CloudWatch alarms" aws_r cloudwatch describe-alarms --alarm-name-prefix chopee- --query 'MetricAlarms[].AlarmName' --output text
query "CloudWatch dashboards" aws_r cloudwatch list-dashboards --dashboard-name-prefix chopee --query 'DashboardEntries[].DashboardName' --output text
query "CloudTrail trails" aws_r cloudtrail describe-trails --query "trailList[?starts_with(Name,'chopee')].Name" --output text
query "SSM parameters" aws_r ssm describe-parameters --parameter-filters "Key=Name,Option=BeginsWith,Values=/chopee" --query 'Parameters[].Name' --output text
query "S3 buckets" aws s3api list-buckets --query "Buckets[?starts_with(Name,'chopee-')].Name" --output text

if [ "$FAIL" -eq 0 ]; then echo "VERIFY_EMPTY: clean"; else echo "VERIFY_EMPTY: NOT clean"; fi
exit "$FAIL"
