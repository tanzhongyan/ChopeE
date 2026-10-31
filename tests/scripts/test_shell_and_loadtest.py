"""Shell scripts run against stub CLIs, the k6 script is inspected, storefront helpers run under node."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


BASH = os.environ.get("BASH_BIN") or (
    "C:\\Program Files\\Git\\usr\\bin\\bash.exe"
    if os.name == "nt" and Path("C:/Program Files/Git/bin/bash.exe").exists()
    else "bash"
)


def sh(args, env=None, **kw):
    return subprocess.run([BASH, *map(str, args)], capture_output=True, text=True, env=env, **kw)


@pytest.mark.parametrize("name", ["push_images.sh", "verify_empty.sh", "run_demo.sh", "stop_checkout_task.sh"])
def test_help_and_syntax(name):
    assert sh(["-n", SCRIPTS / name]).returncode == 0
    r = sh([SCRIPTS / name, "--help"])
    assert r.returncode == 0 and "Usage" in r.stdout


def test_push_images_dry_run_builds_arm64_for_both_services():
    r = sh([SCRIPTS / "push_images.sh", "run1", "--dry-run"])
    assert r.returncode == 0
    assert r.stdout.count("--platform linux/arm64") == 2
    assert "chopee-catalog-cart:run1" in r.stdout and "chopee-checkout:run1" in r.stdout
    # copy-only Dockerfiles need the aarch64 wheels installed on the host first
    assert r.stdout.count("manylinux2014_aarch64") == 2
    assert r.stdout.index("pip install") < r.stdout.index("docker buildx")


def test_run_demo_requires_run_id():
    assert sh([SCRIPTS / "run_demo.sh"]).returncode == 2


def test_run_demo_dry_run_ends_with_destroy_then_verify():
    r = sh([SCRIPTS / "run_demo.sh", "--run-id", "t1", "--dry-run", "--operator-cidr", "auto"])
    assert r.returncode == 0, r.stderr
    out = r.stdout
    order = [out.index(s) for s in ("terraform -chdir", "push_images.sh", "seed_catalog.py", "smoke.py",
                                    "destroy -auto-approve", "verify_empty.sh")]
    assert order == sorted(order)
    assert out.rindex("verify_empty.sh") > out.rindex("destroy -auto-approve")
    assert "image_tag=t1" in out


# ---- stubbed CLIs: prove teardown runs on failure ----
def stub_env(tmp_path, fail_on="", leftover=False, ecs_cluster="", default_schedule="", scheduler_error="",
             aws_error_on=""):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    for tool in ("terraform", "docker", "curl", "pip"):
        (bindir / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\n'
                                   f'case " $* " in *" $FAIL_ON "*) [ -n "$FAIL_ON" ] && exit 1;; esac\nexit 0\n')
    (bindir / "terraform").write_text(
        f'#!/bin/sh\necho "terraform $*" >> "{log}"\n'
        'if [ -n "$FAIL_ON" ] && { [ "$FAIL_ON" = "$3" ] || [ "$FAIL_ON" = "$2" ]; }; then exit 1; fi\n'
        'case "$*" in *"output -json"*) echo "{}" ;; esac\nexit 0\n')
    (bindir / "aws").write_text(f'''#!/bin/sh
echo "aws $*" >> "{log}"
case "$AWS_ERROR_ON" in
  "") ;;
  *) case "$*" in *"$AWS_ERROR_ON"*) echo "AccessDeniedException: denied" >&2; exit 1;; esac ;;
esac
case "$*" in
  *"ecs list-clusters"*)
    [ -n "$ECS_CLUSTER" ] && echo "$ECS_CLUSTER" ;;
  *"scheduler list-schedules"*)
    if [ -n "$SCHEDULER_ERROR" ]; then echo "$SCHEDULER_ERROR" >&2; exit 1; fi
    [ -n "$DEFAULT_SCHEDULE" ] && echo "$DEFAULT_SCHEDULE" ;;
  *list-queues*)
    [ "$SQS_LEFTOVER" = 1 ] && echo "https://sqs/chopee-orders.fifo" ;;
esac
exit 0
''')
    for f in bindir.iterdir():
        f.chmod(0o755)
    py = bindir / "fakepython"
    py.write_text(f'#!/bin/sh\necho "py $*" >> "{log}"\n'
                  'case "$*" in *-c*) echo fake-id;; esac\n[ "$FAIL_ON" = "smoke" ] && case "$*" in *smoke.py*) exit 1;; esac\nexit 0\n')
    py.chmod(0o755)
    git_extra = f"C:\\Program Files\\Git\\bin{os.pathsep}C:\\Program Files\\Git\\usr\\bin{os.pathsep}" if os.name == "nt" else ""
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{git_extra}{os.environ['PATH']}", "PYTHON": str(py), "FAIL_ON": fail_on,
           "AWS_REGION": "ap-southeast-1", "ECS_CLUSTER": ecs_cluster, "DEFAULT_SCHEDULE": default_schedule,
           "SCHEDULER_ERROR": scheduler_error, "SQS_LEFTOVER": str(int(leftover)), "AWS_ERROR_ON": aws_error_on}
    return env, log


@pytest.mark.parametrize("fail_on", ["", "smoke", "validate", "apply"])
def test_run_demo_always_tears_down(tmp_path, fail_on):
    env, log = stub_env(tmp_path, fail_on)
    # keep the stack dir so `-chdir` resolves, and avoid a real wait on the watchdog
    env["TEARDOWN_AFTER_SECONDS"] = "3600"
    r = sh([SCRIPTS / "run_demo.sh", "--run-id", "t1", "--tfvars", tmp_path / "x.tfvars"], env=env)
    calls = log.read_text()
    assert "destroy -auto-approve" in calls, r.stderr
    assert calls.index("destroy -auto-approve") < calls.rindex("aws ")  # verify_empty ran after destroy
    assert (r.returncode == 0) == (fail_on == "")


def test_run_demo_fails_when_destroy_keeps_failing(tmp_path):
    env, log = stub_env(tmp_path, "destroy")
    r = sh([SCRIPTS / "run_demo.sh", "--run-id", "t1", "--tfvars", tmp_path / "x.tfvars"], env=env)
    assert r.returncode == 1 and log.read_text().count("destroy -auto-approve") == 2
    assert "FAILED" in r.stderr


def test_verify_empty_clean_and_leftover(tmp_path):
    env, _ = stub_env(tmp_path)
    ok = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env)
    assert ok.returncode == 0 and "VERIFY_EMPTY: clean" in ok.stdout
    assert "NOTE     empty state is not proof" in ok.stdout
    env2, _ = stub_env(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, leftover=True)
    bad = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env2)
    assert bad.returncode == 1 and "LEFTOVER SQS queues" in bad.stdout


def test_verify_empty_rejects_missing_tf_dir(tmp_path):
    env, log = stub_env(tmp_path)
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path / "missing"], env=env)
    assert r.returncode == 2
    assert "directory not found" in r.stderr and "VERIFY_EMPTY: NOT clean" in r.stdout
    assert not log.exists()  # fail before any cloud call


def test_verify_empty_rejects_tf_dir_without_a_value(tmp_path):
    env, log = stub_env(tmp_path)
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir"], env=env)
    assert r.returncode == 2 and "--tf-dir needs a value" in r.stderr
    assert not log.exists()


def test_verify_empty_fails_on_generic_aws_query_error(tmp_path):
    env, _ = stub_env(tmp_path, aws_error_on="list-queues")
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env)
    assert r.returncode == 1 and "ERROR    SQS queues" in r.stdout
    assert "VERIFY_EMPTY: NOT clean" in r.stdout


def test_verify_empty_detects_exact_demo_cluster(tmp_path):
    env, log = stub_env(tmp_path, ecs_cluster="arn:aws:ecs:ap-southeast-1:123456789012:cluster/chopee")
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env)
    assert r.returncode == 1 and "LEFTOVER ECS clusters" in r.stdout
    assert "ends_with(@,'/chopee')" in log.read_text()


def test_verify_empty_checks_default_group_report_schedule(tmp_path):
    env, log = stub_env(tmp_path, default_schedule="chopee-report-daily")
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env)
    assert r.returncode == 1 and "LEFTOVER scheduler schedules" in r.stdout
    assert "scheduler list-schedules --group-name default --name-prefix chopee" in log.read_text()


def test_verify_empty_fails_on_scheduler_schedule_api_error(tmp_path):
    env, _ = stub_env(tmp_path, scheduler_error="AccessDeniedException: denied")
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env)
    assert r.returncode == 1 and "ERROR    scheduler schedules" in r.stdout


def test_verify_empty_covers_plan_04_resources():
    text = (SCRIPTS / "verify_empty.sh").read_text()
    for needle in ("terraform", "resourcegroupstaggingapi", "us-east-1", "/aws/lambda/chopee-", "/ecs/chopee-",
                   "ecr", "scheduler", "cognito-idp", "cloudfront", "elbv2", "dynamodb", "sns", "sqs", "s3api",
                   "cloudwatch", "cloudtrail", "ecs", "ec2", "lambda"):
        assert needle in text, needle


# Scheduler deletion is asynchronous. Stub all cloud/state commands AND sleep so
# these tests exercise the real verifier without AWS calls, mutations or delays.
def scheduler_stub_env(tmp_path, responses, *, error_at=0, leftover=False):
    env, log = stub_env(tmp_path)
    snapshots = tmp_path / "scheduler"
    snapshots.mkdir()
    (snapshots / "count").write_text("0")
    for i, response in enumerate(responses, 1):
        (snapshots / str(i)).write_text(response)
    (snapshots / "last").write_text(responses[-1])
    (snapshots / "current").write_text(responses[0])
    bindir = tmp_path / "bin"
    (bindir / "aws").write_text('''#!/bin/sh
echo "aws $*" >> "$STUB_CALLS"
case "$*" in
  *"scheduler list-schedule-groups"*)
    count=$(cat "$SCHEDULER_STUB/count")
    count=$((count + 1))
    echo "$count" > "$SCHEDULER_STUB/count"
    if [ "$count" -eq "$SCHEDULER_ERROR_AT" ]; then
      echo "AccessDeniedException: scheduler listing denied" >&2
      exit 1
    fi
    snapshot="$SCHEDULER_STUB/$count"
    [ -f "$snapshot" ] || snapshot="$SCHEDULER_STUB/last"
    cp "$snapshot" "$SCHEDULER_STUB/current"
    cat "$snapshot"
    ;;
  *"resourcegroupstaggingapi get-resources"*)
    # The group is also tagged until it disappears. Polling must happen before
    # the tag sweep, otherwise a resolved deletion still leaves FAIL latched.
    if grep -q chopee "$SCHEDULER_STUB/current"; then
      echo "arn:aws:scheduler:ap-southeast-1:123456789012:schedule-group/chopee-expiry"
    fi
    ;;
  *list-queues*)
    [ "$SQS_LEFTOVER" = 1 ] && echo "https://sqs/chopee-orders.fifo"
    ;;
esac
exit 0
''')
    sleep = bindir / "sleep"
    sleep.write_text('#!/bin/sh\necho "sleep $*" >> "$STUB_CALLS"\nexit 0\n')
    sleep.chmod(0o755)
    env.update(STUB_CALLS=str(log), SCHEDULER_STUB=str(snapshots),
               SCHEDULER_ERROR_AT=str(error_at), SQS_LEFTOVER=str(int(leftover)))
    return env, log


def test_verify_empty_waits_for_deleting_scheduler_groups_before_tag_sweep(tmp_path):
    env, log = scheduler_stub_env(tmp_path, [
        "chopee-expiry\tDELETING\nchopee-extra\tDELETING\n",
        "chopee-expiry\tDELETING\n",
        "",
    ])
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env, timeout=30)
    calls = log.read_text()
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("WAIT") == 2 and "ok       scheduler groups" in r.stdout
    assert "VERIFY_EMPTY: clean" in r.stdout
    assert calls.count("scheduler list-schedule-groups") == 3
    assert [line for line in calls.splitlines() if line.startswith("sleep ")] == ["sleep 2", "sleep 4"]
    assert calls.rindex("scheduler list-schedule-groups") < calls.index("resourcegroupstaggingapi")
    assert "ScheduleGroups[].[Name,State]" in calls
    assert "delete-" not in calls and "destroy" not in calls


@pytest.mark.parametrize("response", ["", "None\n"])
def test_verify_empty_does_not_wait_when_scheduler_is_empty(tmp_path, response):
    env, log = scheduler_stub_env(tmp_path, [response])
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WAIT" not in r.stdout and "sleep " not in log.read_text()


@pytest.mark.parametrize("groups", [
    "chopee-expiry\tACTIVE\n",
    "chopee-expiry\tDELETING\nchopee-other\tACTIVE\n",
    "chopee-expiry\tUNKNOWN\n",
    "chopee-expiry\n",  # missing state must not be assumed to be DELETING
])
def test_verify_empty_does_not_retry_active_or_unknown_scheduler_groups(tmp_path, groups):
    env, log = scheduler_stub_env(tmp_path, [groups])
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env, timeout=30)
    assert r.returncode == 1 and "LEFTOVER scheduler groups" in r.stdout
    assert "VERIFY_EMPTY: NOT clean" in r.stdout and "WAIT" not in r.stdout
    assert log.read_text().count("scheduler list-schedule-groups") == 1
    assert "sleep " not in log.read_text()


def test_verify_empty_scheduler_wait_is_bounded(tmp_path):
    env, log = scheduler_stub_env(tmp_path, ["chopee-expiry\tDELETING\n"])
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env, timeout=30)
    calls = log.read_text()
    assert r.returncode == 1 and "VERIFY_EMPTY: NOT clean" in r.stdout
    assert "LEFTOVER scheduler groups" in r.stdout and "DELETING" in r.stdout
    assert "exhausted" in r.stdout.lower()
    assert calls.count("scheduler list-schedule-groups") == 6
    assert [line for line in calls.splitlines() if line.startswith("sleep ")] == [
        "sleep 2", "sleep 4", "sleep 8", "sleep 16", "sleep 30",
    ]


@pytest.mark.parametrize("error_at", [1, 2])
def test_verify_empty_fails_on_scheduler_api_error_even_after_waiting(tmp_path, error_at):
    env, log = scheduler_stub_env(tmp_path, ["chopee-expiry\tDELETING\n"], error_at=error_at)
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env, timeout=30)
    assert r.returncode == 1 and "VERIFY_EMPTY: NOT clean" in r.stdout
    assert "ERROR    scheduler groups" in r.stdout and "AccessDeniedException" in r.stdout
    assert log.read_text().count("scheduler list-schedule-groups") == error_at


def test_verify_empty_scheduler_recovery_does_not_hide_other_leftovers(tmp_path):
    env, log = scheduler_stub_env(tmp_path, ["chopee-expiry\tDELETING\n", ""], leftover=True)
    r = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path], env=env, timeout=30)
    assert r.returncode == 1 and "VERIFY_EMPTY: NOT clean" in r.stdout
    assert "ok       scheduler groups" in r.stdout and "LEFTOVER SQS queues" in r.stdout
    assert "describe-log-groups" in log.read_text()  # the remaining checks still run


# ---- task-stop recovery (SRE-7) ----
def ecs_stub_env(tmp_path, *, cluster="arn:aws:ecs:ap-southeast-1:123456789012:cluster/chopee",
                 service="arn:aws:ecs:ap-southeast-1:123456789012:service/chopee/chopee-checkout",
                 old_task="arn:aws:ecs:ap-southeast-1:123456789012:task/chopee/old",
                 new_task="arn:aws:ecs:ap-southeast-1:123456789012:task/chopee/new",
                 old_status="STOPPED", running=2, desired=2, ready_after=1, service_error=False, task_error=False, describe_error=False):
    env, log = stub_env(tmp_path)
    state = tmp_path / "ecs"
    state.mkdir()
    (state / "services").write_text("0")
    (tmp_path / "bin" / "aws").write_text(f'''#!/bin/sh
echo "aws $*" >> "{log}"
case "$*" in
  *"ecs list-clusters"*) [ -n "{cluster}" ] && echo "{cluster}" ;;
  *"ecs list-services"*) [ -n "{service}" ] && echo "{service}" ;;
  *"ecs list-tasks"*)
    if grep -q "ecs stop-task" "{log}"; then
      if [ "{int(task_error)}" = 1 ]; then echo "AccessDeniedException: denied" >&2; exit 1; fi
      [ -n "{new_task}" ] && echo "{new_task}"
    else [ -n "{old_task}" ] && echo "{old_task}"; fi ;;
  *"ecs stop-task"*) exit 0 ;;
  *"ecs describe-services"*)
    if [ "{int(service_error)}" = 1 ]; then echo "AccessDeniedException: denied" >&2; exit 1; fi
    n=$(cat "{state}/services"); n=$((n + 1)); echo "$n" > "{state}/services"
    if [ "$n" -ge {ready_after} ]; then printf '{running}\\t{desired}\\n'; else printf '0\\t{desired}\\n'; fi ;;
  *"ecs describe-tasks"*)
    if [ "{int(describe_error)}" = 1 ]; then echo "AccessDeniedException: denied" >&2; exit 1; fi
    echo "{old_status}" ;;
esac
exit 0
''')
    sleep = tmp_path / "bin" / "sleep"
    sleep.write_text(f'#!/bin/sh\necho "sleep $*" >> "{log}"\nexit 0\n')
    sleep.chmod(0o755)
    return env, log


def test_stop_checkout_task_verifies_replacement(tmp_path):
    env, log = ecs_stub_env(tmp_path)
    r = sh([SCRIPTS / "stop_checkout_task.sh"], env=env, timeout=30)
    calls = log.read_text()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS:" in r.stdout and "task/chopee/new" in r.stdout
    assert "ecs stop-task" in calls and "ecs describe-services" in calls
    assert calls.index("ecs stop-task") < calls.index("ecs describe-services")


@pytest.mark.parametrize("kwargs", [
    {"cluster": ""},
    {"service": ""},
    {"old_task": ""},
])
def test_stop_checkout_task_refuses_unknown_targets(tmp_path, kwargs):
    env, log = ecs_stub_env(tmp_path, **kwargs)
    r = sh([SCRIPTS / "stop_checkout_task.sh"], env=env, timeout=30)
    assert r.returncode == 1 and "ERROR" in r.stderr
    assert "ecs stop-task" not in log.read_text()


@pytest.mark.parametrize("kwargs,detail", [
    ({"old_status": "RUNNING"}, "old=RUNNING"),
    ({"new_task": ""}, "old=STOPPED"),
    ({"running": 1, "desired": 2}, "running=1 desired=2"),
])
def test_stop_checkout_task_requires_each_recovery_gate(tmp_path, kwargs, detail):
    env, log = ecs_stub_env(tmp_path, **kwargs)
    r = sh([SCRIPTS / "stop_checkout_task.sh", "--timeout", "1", "--poll", "0"], env=env, timeout=30)
    assert r.returncode == 1 and "FAIL: replacement not confirmed" in r.stderr
    assert detail in r.stderr
    assert "PASS:" not in r.stdout and "ecs stop-task" in log.read_text()


@pytest.mark.parametrize("flag,value", [("--timeout", "soon"), ("--poll", "-1")])
def test_stop_checkout_task_rejects_bad_numeric_flags(tmp_path, flag, value):
    env, log = ecs_stub_env(tmp_path)
    r = sh([SCRIPTS / "stop_checkout_task.sh", flag, value], env=env, timeout=30)
    assert r.returncode == 2 and "non-negative integer" in r.stderr
    assert not log.exists()


def test_stop_checkout_task_fails_without_replacement(tmp_path):
    env, log = ecs_stub_env(tmp_path, ready_after=999, new_task="")
    r = sh([SCRIPTS / "stop_checkout_task.sh", "--timeout", "0"], env=env, timeout=30)
    assert r.returncode == 1 and "FAIL: replacement not confirmed" in r.stderr
    assert "ecs stop-task" in log.read_text()


def test_stop_checkout_task_fails_on_service_api_error(tmp_path):
    env, _ = ecs_stub_env(tmp_path, service_error=True)
    r = sh([SCRIPTS / "stop_checkout_task.sh"], env=env, timeout=30)
    assert r.returncode == 1 and "ERROR describe-services" in r.stderr


def test_stop_checkout_task_fails_on_task_api_error(tmp_path):
    env, _ = ecs_stub_env(tmp_path, task_error=True)
    r = sh([SCRIPTS / "stop_checkout_task.sh"], env=env, timeout=30)
    assert r.returncode == 1 and "ERROR list-tasks" in r.stderr


def test_stop_checkout_task_fails_on_describe_task_api_error(tmp_path):
    env, _ = ecs_stub_env(tmp_path, describe_error=True)
    r = sh([SCRIPTS / "stop_checkout_task.sh"], env=env, timeout=30)
    assert r.returncode == 1 and "ERROR describe-tasks" in r.stderr


# ---- k6 ----
@pytest.mark.skipif(not shutil.which("k6"), reason="k6 not installed")
def test_k6_inspect_scenarios():
    r = subprocess.run(["k6", "inspect", str(ROOT / "loadtest" / "checkout_burst.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import json

    sc = json.loads(r.stdout)["scenarios"]
    assert set(sc) == {"ramp", "hold", "down"}
    assert sc["hold"]["rate"] == 500 and sc["hold"]["startTime"] == "30s" and sc["down"]["startTime"] == "1m30s"
    assert sc["hold"]["maxVUs"] == 1000 and sc["hold"]["preAllocatedVUs"] == 300


# ---- storefront helpers ----
@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_storefront_helpers_under_node():
    js = (
        "const h=require(process.argv[1]);const a=require('assert');"
        "a.equal(h.formatPrice(650,'SGD'),'S$6.50');a.equal(h.clampQty(9),5);a.equal(h.clampQty(-1),0);"
        "a.equal(h.countdown(1000+65000,1000),'1:05');a.equal(h.countdown(0,1000),'0:00');"
        "a.equal(h.escapeHtml('<b>&\"'),'&lt;b&gt;&amp;&quot;');a.ok(/^[0-9a-f-]{36}$/.test(h.uuid()));"
        "a.deepEqual(h.checkoutBody({items:[{sku:'A',quantity:2,price:5}]}),{items:[{sku:'A',quantity:2}]});"
        "a.ok(h.isTerminal('PAID')&&!h.isTerminal('PENDING_PAYMENT'));"
        "a.equal(h.authErrorMessage({__type:'NotAuthorizedException'}),'Wrong email or password.');"
    )
    r = subprocess.run(["node", "-e", js, str(ROOT / "storefront" / "app.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_storefront_order_flows_under_node():
    test_file = ROOT / "tests" / "scripts" / "storefront_flow.test.js"
    r = subprocess.run(["node", "--test", str(test_file)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_storefront_has_no_binaries_and_example_config():
    import json

    files = sorted(p.name for p in (ROOT / "storefront").iterdir() if p.is_file() and p.name != "config.json")
    assert files == ["app.js", "config.example.json", "index.html", "styles.css"]
    cfg = json.loads((ROOT / "storefront" / "config.example.json").read_text())
    assert set(cfg) == {"apiBase", "region", "userPoolId", "clientId"} and cfg["apiBase"] == "/api"
