"""Shell scripts run against stub CLIs, the k6 script is inspected, storefront helpers run under node."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def sh(args, env=None, **kw):
    return subprocess.run(["bash", *map(str, args)], capture_output=True, text=True, env=env, **kw)


@pytest.mark.parametrize("name", ["push_images.sh", "verify_empty.sh", "run_demo.sh"])
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
def stub_env(tmp_path, fail_on="", leftover=False):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    for tool in ("terraform", "docker", "curl", "pip"):
        (bindir / tool).write_text(f'#!/usr/bin/env bash\necho "{tool} $*" >> "{log}"\n'
                                   f'case " $* " in *" $FAIL_ON "*) [ -n "$FAIL_ON" ] && exit 1;; esac\nexit 0\n')
    (bindir / "terraform").write_text(
        f'#!/usr/bin/env bash\necho "terraform $*" >> "{log}"\n'
        'if [ -n "$FAIL_ON" ] && { [ "$FAIL_ON" = "$3" ] || [ "$FAIL_ON" = "$2" ]; }; then exit 1; fi\n'
        'case "$*" in *"output -json"*) echo "{}" ;; esac\nexit 0\n')
    (bindir / "aws").write_text(
        f'#!/usr/bin/env bash\necho "aws $*" >> "{log}"\n'
        + ('case "$*" in *list-queues*) echo "https://sqs/chopee-orders.fifo";; esac\n' if leftover else "")
        + "exit 0\n")
    for f in bindir.iterdir():
        f.chmod(0o755)
    py = bindir / "fakepython"
    py.write_text(f'#!/usr/bin/env bash\necho "py $*" >> "{log}"\n'
                  'case "$*" in *-c*) echo fake-id;; esac\n[ "$FAIL_ON" = "smoke" ] && case "$*" in *smoke.py*) exit 1;; esac\nexit 0\n')
    py.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "PYTHON": str(py), "FAIL_ON": fail_on,
           "AWS_REGION": "ap-southeast-1"}
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
    ok = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path / "none"], env=env)
    assert ok.returncode == 0 and "VERIFY_EMPTY: clean" in ok.stdout
    env2, _ = stub_env(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, leftover=True)
    bad = sh([SCRIPTS / "verify_empty.sh", "--tf-dir", tmp_path / "none"], env=env2)
    assert bad.returncode == 1 and "LEFTOVER SQS queues" in bad.stdout


def test_verify_empty_covers_plan_04_resources():
    text = (SCRIPTS / "verify_empty.sh").read_text()
    for needle in ("terraform", "resourcegroupstaggingapi", "us-east-1", "/aws/lambda/chopee-", "/ecs/chopee-",
                   "ecr", "scheduler", "cognito-idp", "cloudfront", "elbv2", "dynamodb", "sns", "sqs", "s3api",
                   "cloudwatch", "cloudtrail", "ecs", "ec2", "lambda"):
        assert needle in text, needle


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


def test_storefront_has_no_binaries_and_example_config():
    import json

    files = sorted(p.name for p in (ROOT / "storefront").iterdir())
    assert files == ["app.js", "config.example.json", "index.html", "styles.css"]
    cfg = json.loads((ROOT / "storefront" / "config.example.json").read_text())
    assert set(cfg) == {"apiBase", "region", "userPoolId", "clientId"} and cfg["apiBase"] == "/api"
