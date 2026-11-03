"""Compute and registry regression tests (plan 05c API-9; contracts in plan 06 Sections 5.2 and 6.2).

These parse the Terraform source, not deployed resources.
"""
from __future__ import annotations

from pathlib import Path

import hcl2

MODULES = Path(__file__).resolve().parents[2] / "infra" / "terraform" / "modules"


def parse(rel: str) -> dict:
    with (MODULES / rel).open() as fh:
        return hcl2.load(fh)


def unquote(value):
    if isinstance(value, list):
        return [unquote(v) for v in value]
    return value.strip('"') if isinstance(value, str) else value


def resources(rel: str, kind: str) -> dict:
    out: dict = {}
    for item in parse(rel).get("resource", []):
        for k, v in item.items():
            if k.strip('"') == kind:
                out.update({n.strip('"'): body for n, body in v.items()})
    return out


def services() -> dict:
    for item in parse("compute/main.tf")["locals"]:
        if "services" in item:
            return {k: {a: unquote(b) for a, b in v.items()} for k, v in item["services"].items()}
    raise AssertionError("local.services not found")


def conditions(rule: dict) -> dict:
    out = {}
    for cond in rule["condition"]:
        kind = next(k for k in cond if k != "__is_block__")
        out[kind] = cond[kind][0]
    return out


# ---------------------------------------------------------------- listener rules


def test_listener_rule_paths_match_plan_06():
    svc = services()
    assert svc["catalog_cart"]["paths"] == ["/api/catalog*", "/api/cart*", "/api/healthz"]
    assert svc["checkout"]["paths"] == ["/api/checkout*", "/api/orders*", "/api/demo/*"]
    webhook = resources("compute/main.tf", "aws_lb_listener_rule")["webhook"]
    assert unquote(conditions(webhook)["path_pattern"]["values"]) == ["/api/webhooks/*"]
    assert webhook["action"][0]["target_group_arn"] == '${aws_lb_target_group.svc["checkout"].arn}'


def test_every_rule_except_webhook_requires_origin_verify_header():
    rules = resources("compute/main.tf", "aws_lb_listener_rule")
    assert set(rules) == {"svc", "webhook"}
    header = conditions(rules["svc"])["http_header"]
    assert unquote(header["http_header_name"]) == "X-Origin-Verify"
    assert header["values"] == ["${var.origin_verify_value}"]
    assert "http_header" not in conditions(rules["webhook"])


def test_rule_condition_values_stay_within_alb_quota():
    # ALB quota: 5 condition values per rule (paths + header value).
    for svc in services().values():
        assert len(svc["paths"]) + 1 <= 5


def test_webhook_priority_is_lower_than_service_rules():
    webhook = resources("compute/main.tf", "aws_lb_listener_rule")["webhook"]["priority"]
    assert all(webhook < s["prio"] for s in services().values())


def test_default_action_is_fixed_404():
    action = resources("compute/main.tf", "aws_lb_listener")["http"]["default_action"][0]
    assert unquote(action["type"]) == "fixed-response"
    assert unquote(action["fixed_response"][0]["status_code"]) == "404"


def test_alb_security_group_has_only_two_ingress_rules():
    # The CloudFront prefix list counts ~55 entries toward the SG rule quota (plan 06 Section 6.2).
    ingress = resources("compute/main.tf", "aws_vpc_security_group_ingress_rule")
    alb = [r for r in ingress.values() if r["security_group_id"] == "${aws_security_group.alb.id}"]
    assert sorted(("prefix_list_id" in r, "cidr_ipv4" in r) for r in alb) == [(False, True), (True, False)]
    assert not resources("compute/main.tf", "aws_security_group")["alb"].get("ingress")


# ---------------------------------------------------------------- task definitions and services


def test_task_definitions_are_arm64_linux_with_plan_sizes():
    svc = services()
    assert (svc["catalog_cart"]["cpu"], svc["catalog_cart"]["memory"]) == (512, 1024)
    assert (svc["checkout"]["cpu"], svc["checkout"]["memory"]) == (1024, 2048)
    td = resources("compute/main.tf", "aws_ecs_task_definition")["svc"]
    assert td["for_each"] == "${local.services}"
    assert td["cpu"] == "${each.value.cpu}" and td["memory"] == "${each.value.memory}"
    platform = td["runtime_platform"][0]
    assert (unquote(platform["cpu_architecture"]), unquote(platform["operating_system_family"])) == ("ARM64", "LINUX")


def test_xray_daemon_sidecar_on_checkout_only():
    definition = resources("compute/main.tf", "aws_ecs_task_definition")["svc"]["container_definitions"]
    assert definition.count('name = "xray-daemon"') == 1
    assert 'each.key == "checkout" ? [{name = "xray-daemon"' in definition


def test_services_have_circuit_breaker_public_ip_and_ignore_desired_count():
    svc = resources("compute/main.tf", "aws_ecs_service")["svc"]
    breaker = svc["deployment_circuit_breaker"][0]
    assert breaker["enable"] is True and breaker["rollback"] is True
    assert svc["network_configuration"][0]["assign_public_ip"] is True
    assert svc["lifecycle"][0]["ignore_changes"] == ["desired_count"]



def test_unused_cognito_issuer_env_removed():
    assert "COGNITO_ISSUER" not in str(parse("compute/main.tf")["locals"])


# ---------------------------------------------------------------- autoscaling


def policies() -> dict:
    return resources("compute/main.tf", "aws_appautoscaling_policy")


def test_autoscaling_max_capacity_is_at_most_ten():
    target = resources("compute/main.tf", "aws_appautoscaling_target")["svc"]
    assert target["max_capacity"] <= 10  # 10 + 10 tasks stays inside the 16 vCPU preflight (plan 05c API-6)
    sched = resources("compute/main.tf", "aws_appautoscaling_scheduled_action")["checkout_prescale"]
    assert sched["scalable_target_action"][0]["max_capacity"] <= 10


def test_cpu_policy_targets_60_with_cooldowns():
    cfg = policies()["cpu"]["target_tracking_scaling_policy_configuration"][0]
    assert cfg["target_value"] == 60
    assert unquote(cfg["predefined_metric_specification"][0]["predefined_metric_type"]) == "ECSServiceAverageCPUUtilization"
    assert (cfg["scale_out_cooldown"], cfg["scale_in_cooldown"]) == (30, 300)


def test_checkout_request_count_policy_with_cooldowns():
    policy = policies()["checkout_requests"]
    assert policy["resource_id"] == '${aws_appautoscaling_target.svc["checkout"].resource_id}'
    cfg = policy["target_tracking_scaling_policy_configuration"][0]
    assert cfg["target_value"] == 150
    assert (cfg["scale_out_cooldown"], cfg["scale_in_cooldown"]) == (30, 300)
    spec = cfg["predefined_metric_specification"][0]
    assert unquote(spec["predefined_metric_type"]) == "ALBRequestCountPerTarget"
    assert unquote(spec["resource_label"]) == (
        '${aws_lb.this.arn_suffix}/${aws_lb_target_group.svc["checkout"].arn_suffix}')


# ---------------------------------------------------------------- registry


def test_registry_is_immutable_scanned_and_force_deleted():
    repo = resources("registry/main.tf", "aws_ecr_repository")["this"]
    assert repo["force_delete"] is True
    assert repo["image_scanning_configuration"][0]["scan_on_push"] is True
    assert unquote(repo["image_tag_mutability"]) == "IMMUTABLE"
