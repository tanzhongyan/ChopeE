#!/usr/bin/env bash
# One timed demo run: deploy, seed, smoke test, optional extra step, then ALWAYS tear down and verify.
# Implements plan 06 Section 6.4. Teardown runs from an EXIT/INT/TERM trap, so a failed step, Ctrl-C,
# or the 4 h 15 min watchdog still ends in `terraform destroy -auto-approve` + scripts/verify_empty.sh.
#
# Usage: scripts/run_demo.sh --run-id ID [--tfvars FILE] [--operator-cidr CIDR|auto]
#                            [--then "COMMAND"] [--hold] [--dry-run]
#   --then "CMD"  run CMD after the smoke test (e.g. the k6 burst); outputs are exported as TF_OUTPUTS
#   --hold        pause for Enter after everything else (presenting); teardown follows
#   --dry-run     print the commands instead of running them (teardown still printed last)
# Env: AWS_REGION (ap-southeast-1), PYTHON (python3), TEARDOWN_AFTER_SECONDS (15300 = 4 h 15 min)
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TF="$ROOT/infra/terraform"
PYTHON=${PYTHON:-python3}
REGION=${AWS_REGION:-ap-southeast-1}
DEADLINE=${TEARDOWN_AFTER_SECONDS:-15300}
RUN_ID="" TFVARS="$TF/envs/demo.tfvars" CIDR="" THEN="" HOLD=0 DRY=0

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --run-id) RUN_ID=$2; shift 2 ;;
    --tfvars) TFVARS=$2; shift 2 ;;
    --operator-cidr) CIDR=$2; shift 2 ;;
    --then) THEN=$2; shift 2 ;;
    --hold) HOLD=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$RUN_ID" ] || { echo "--run-id is required" >&2; exit 2; }

step() { echo; echo "=== $* ==="; }
run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }

TORN_DOWN=0 STATUS=0
OUTPUTS=""
VARS=(-var-file="$TFVARS" -var "run_id=$RUN_ID" -var "image_tag=$RUN_ID")  # images are pushed as :RUN_ID

teardown() {
  [ "$TORN_DOWN" = 1 ] && return
  TORN_DOWN=1
  trap '' INT TERM
  if [ -n "${WATCHDOG_PID:-}" ]; then
    # Stop the watchdog subshell first (so it cannot signal us), then its sleep.
    kids=$(pgrep -P "$WATCHDOG_PID" 2>/dev/null)
    kill -KILL "$WATCHDOG_PID" 2>/dev/null
    # shellcheck disable=SC2086
    [ -n "$kids" ] && kill $kids 2>/dev/null
    wait "$WATCHDOG_PID" 2>/dev/null
  fi
  step "teardown"
  run terraform -chdir="$TF" init -input=false >/dev/null 2>&1 || true
  # Destroy even after a partial apply; harmless on an empty state.
  if ! run terraform -chdir="$TF" destroy -auto-approve "${VARS[@]}"; then
    echo "DESTROY FAILED - retrying once" >&2
    run terraform -chdir="$TF" destroy -auto-approve "${VARS[@]}" || STATUS=1
  fi
  run "$ROOT/scripts/verify_empty.sh" || STATUS=1
  [ "$STATUS" = 0 ] && echo "teardown verified clean" || echo "TEARDOWN OR VERIFY FAILED: act now, resources may still be billing" >&2
}
on_signal() { echo "interrupted" >&2; STATUS=1; exit 1; }
on_exit() { local rc=$?; [ "$rc" != 0 ] && STATUS=1; teardown; exit "$STATUS"; }
trap on_signal INT TERM
trap on_exit EXIT

if [ "$DRY" = 0 ]; then
  # Hard stop: CloudFront deletion is slow, so teardown must start by the deadline.
  ( sleep "$DEADLINE" >/dev/null 2>&1; echo "deadline reached, starting teardown" >&2; kill -TERM $$ ) &
  WATCHDOG_PID=$!
fi

if [ "$CIDR" = auto ]; then
  step "operator IP"
  if [ "$DRY" = 1 ]; then CIDR="<operator-ip>/32"; echo "+ curl -s https://checkip.amazonaws.com"
  else CIDR="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')/32" || exit 1; fi
fi
[ -n "$CIDR" ] && VARS+=(-var "operator_cidr=$CIDR")

step "terraform fmt/init/validate"
run terraform -chdir="$TF" fmt -check || exit 1
run terraform -chdir="$TF" init || exit 1
run terraform -chdir="$TF" validate || exit 1

step "stage 1: registry"
run terraform -chdir="$TF" plan -target=module.registry "${VARS[@]}" -out=tfplan || exit 1
run terraform -chdir="$TF" apply tfplan || exit 1

step "build and push images"
run "$ROOT/scripts/push_images.sh" "$RUN_ID" || exit 1

step "stage 2: everything"
run terraform -chdir="$TF" plan "${VARS[@]}" -out=tfplan || exit 1
run terraform -chdir="$TF" apply tfplan || exit 1
if [ "$DRY" = 0 ]; then
  OUTPUTS="$(mktemp)"; terraform -chdir="$TF" output -json > "$OUTPUTS" || exit 1
  export TF_OUTPUTS="$OUTPUTS"
else
  OUTPUTS="<tf-outputs.json>"; echo "+ terraform output -json > $OUTPUTS"
fi
echo "!! Confirm the ops-alert email subscription now (it is recreated every run)."

step "seed"
run "$PYTHON" "$ROOT/scripts/seed_catalog.py" --region "$REGION" || exit 1
POOL_ARGS=()
if [ "$DRY" = 0 ]; then
  POOL_ARGS=(--user-pool-id "$($PYTHON -c "import json,sys;print(json.load(open(sys.argv[1]))['user_pool_id']['value'])" "$OUTPUTS")"
             --client-id "$($PYTHON -c "import json,sys;print(json.load(open(sys.argv[1]))['client_id']['value'])" "$OUTPUTS")")
else
  POOL_ARGS=(--user-pool-id "<user_pool_id>" --client-id "<client_id>")
fi
run "$PYTHON" "$ROOT/scripts/create_test_users.py" "${POOL_ARGS[@]}" --count 1000 --region "$REGION" \
  --out "$ROOT/loadtest/tokens.json" || exit 1

step "smoke test"
run "$PYTHON" "$ROOT/scripts/smoke.py" --tf-outputs "$OUTPUTS" --region "$REGION" || exit 1

if [ -n "$THEN" ]; then
  step "extra step: $THEN"
  if [ "$DRY" = 1 ]; then echo "+ $THEN"; else bash -c "$THEN" || exit 1; fi
fi
if [ "$HOLD" = 1 ] && [ "$DRY" = 0 ]; then
  step "holding (stack is billing)"
  read -r -p "Press Enter to tear down... " _ || true
fi
exit 0
