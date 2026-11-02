"""Configuration regression tests for the Owner 5 security controls (plan 05b).

These parse the Terraform source, not deployed resources. They pin the Cognito
token lifetime and client settings, per-service secret access, key-scoped IAM,
and CloudTrail integrity.
"""
from __future__ import annotations

from pathlib import Path

import hcl2

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "infra" / "terraform" / "modules"


def parse(rel: str) -> dict:
    with (MODULES / rel).open() as fh:
        return hcl2.load(fh)


def blocks(parsed: dict, section: str, kind: str) -> dict:
    out: dict = {}
    for item in parsed.get(section, []):
        out.update(item.get(f'"{kind}"', {}))
    return out


def unquote(value):
    if isinstance(value, list):
        return [unquote(v) for v in value]
    return value.strip('"') if isinstance(value, str) else value


def statements_for(policy: dict, service: str) -> list[dict]:
    """Static statements plus the dynamic ones whose for_each selects ``service``."""
    out = list(policy.get("statement", []))
    for dyn in policy.get("dynamic", []):
        body = dyn['"statement"']
        if f'each.key == \\"{service}\\"' in body["for_each"] or f'each.key == "{service}"' in body["for_each"]:
            out += body["content"]
    return out


def leading_keys(statement: dict) -> list[str] | None:
    for cond in statement.get("condition", []):
        if unquote(cond["variable"]) == "dynamodb:LeadingKeys":
            assert unquote(cond["test"]) == "ForAllValues:StringLike"
            return unquote(cond["values"])
    return None


# ---------------------------------------------------------------- SEC-1 Cognito


def test_cognito_pool_is_lite_with_email_sign_in():
    pool = blocks(parse("identity/main.tf"), "resource", "aws_cognito_user_pool")['"this"']
    assert unquote(pool["user_pool_tier"]) == "LITE"
    assert unquote(pool["username_attributes"]) == ["email"]
    assert pool["password_policy"][0]["minimum_length"] >= 8


def test_cognito_client_token_lifetime_and_hardening():
    client = blocks(parse("identity/main.tf"), "resource", "aws_cognito_user_pool_client")['"web"']
    units = client["token_validity_units"][0]
    # 3-hour access tokens so pre-minted k6 tokens outlive a load run (plan 06 Section 6.2).
    assert (client["access_token_validity"], unquote(units["access_token"])) == (3, "hours")
    assert (client["id_token_validity"], unquote(units["id_token"])) == (3, "hours")
    assert (client["refresh_token_validity"], unquote(units["refresh_token"])) == (1, "days")
    assert client["generate_secret"] is False  # public SPA client
    assert unquote(client["prevent_user_existence_errors"]) == "ENABLED"
    assert client["enable_token_revocation"] is True
    assert sorted(unquote(client["explicit_auth_flows"])) == [
        "ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_PASSWORD_AUTH"]


# ---------------------------------------------------------------- SEC-3/4 compute


def compute() -> dict:
    return parse("compute/main.tf")


def compute_locals() -> dict:
    out: dict = {}
    for item in compute().get("locals", []):
        out.update(item)
    return out


def test_only_checkout_receives_secrets():
    secrets = compute_locals()["container_secrets"]
    assert secrets["catalog_cart"] == []
    assert sorted(unquote(s["name"]) for s in secrets["checkout"]) == ["LOG_SALT", "WEBHOOK_SECRET"]
    assert all("WEBHOOK_SECRET_PARAM" not in str(e) for e in compute_locals()["checkout_env"])


def test_execution_roles_are_per_service_and_read_only_their_secrets():
    parsed = compute()
    roles = blocks(parsed, "resource", "aws_iam_role")
    assert roles['"execution"']["for_each"] == "${local.services}"
    ssm = blocks(parsed, "data", "aws_iam_policy_document")['"execution_ssm"']
    assert ssm["for_each"] == "${local.secret_arns}"
    assert ssm["statement"][0]["resources"] == "${each.value}"
    assert unquote(ssm["statement"][0]["actions"]) == ["ssm:GetParameters"]
    task_def = blocks(parsed, "resource", "aws_ecs_task_definition")['"svc"']
    assert task_def["execution_role_arn"] == "${aws_iam_role.execution[each.key].arn}"


def test_task_roles_are_key_scoped_and_hold_no_ssm():
    task = blocks(compute(), "data", "aws_iam_policy_document")['"task"']
    for service in ("catalog_cart", "checkout"):
        for st in statements_for(task, service):
            actions = unquote(st["actions"])
            assert not any(a.startswith("ssm:") for a in actions), service  # secrets come via the execution role
            if any(a.startswith("dynamodb:") for a in actions):
                assert leading_keys(st), f"{service}: {actions} must be scoped by dynamodb:LeadingKeys"
    checkout = statements_for(task, "checkout")
    scopes = {unquote(st["actions"])[0]: leading_keys(st) for st in checkout if leading_keys(st)}
    assert scopes == {"dynamodb:GetItem": ["ORDER#*"], "dynamodb:Query": ["CUSTOMER#*"]}


def test_only_checkout_can_write_xray():
    task = blocks(compute(), "data", "aws_iam_policy_document")['"task"']
    xray = lambda svc: any(a.startswith("xray:") for st in statements_for(task, svc) for a in unquote(st["actions"]))
    assert xray("checkout") and not xray("catalog_cart")


def test_notify_consumers_write_only_dedupe_markers():
    consumer = blocks(parse("functions/main.tf"), "data", "aws_iam_policy_document")['"consumer"']
    ddb = [st for st in consumer["statement"] if any(a.startswith("dynamodb:") for a in unquote(st["actions"]))]
    assert len(ddb) == 1 and unquote(ddb[0]["actions"]) == ["dynamodb:PutItem"]
    assert leading_keys(ddb[0]) == ["CONSUMED#*"]


# ---------------------------------------------------------------- SEC-5 CloudTrail


def test_cloudtrail_validates_log_files_and_bucket_is_tls_only():
    parsed = parse("observe/audit.tf")
    trail = blocks(parsed, "resource", "aws_cloudtrail")['"this"']
    assert trail["enable_log_file_validation"] is True and trail["enable_logging"] is True
    bucket = blocks(parsed, "resource", "aws_s3_bucket")['"audit"']
    assert bucket["force_destroy"] is True  # teardown must never block (AGENTS.md)
    policy = blocks(parsed, "data", "aws_iam_policy_document")['"audit"']
    deny = [st for st in policy["statement"] if unquote(st.get("effect")) == "Deny"]
    assert len(deny) == 1
    cond = deny[0]["condition"][0]
    assert (unquote(cond["variable"]), unquote(cond["values"])) == ("aws:SecureTransport", ["false"])
    pab = blocks(parsed, "resource", "aws_s3_bucket_public_access_block")['"audit"']
    assert all(pab[k] is True for k in ("block_public_acls", "block_public_policy", "ignore_public_acls",
                                        "restrict_public_buckets"))
