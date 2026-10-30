"""Configuration regression tests for the demo observability stack (SRE-5).

These parse the Terraform source, not deployed resources. They protect the
dashboard and alarm contracts that plan 04 requires: order outcomes from the
worker's EMF namespace, notification failures, the ops-topic action and the
documented thresholds.
"""
from __future__ import annotations

import re
from pathlib import Path

import hcl2

ROOT = Path(__file__).resolve().parents[2]
OBSERVE = ROOT / "infra" / "terraform" / "modules" / "observe"
WORKER = ROOT / "functions" / "order_worker" / "handler.py"


def parse(name: str) -> dict:
    with (OBSERVE / name).open() as fh:
        return hcl2.load(fh)


def resource_blocks(parsed: dict, kind: str) -> dict:
    out: dict = {}
    for item in parsed.get("resource", []):
        out.update(item.get(f'"{kind}"', {}))
    return out


def test_dashboard_parses_and_has_expected_widget_count():
    parsed = parse("dashboard.tf")
    dashboards = resource_blocks(parsed, "aws_cloudwatch_dashboard")
    assert list(dashboards) == ['"this"']
    assert dashboards['"this"']["dashboard_name"] == '"chopee"'
    text = (OBSERVE / "dashboard.tf").read_text()
    assert len(re.findall(r'type\s*=\s*"metric"', text)) == 8


def test_dashboard_charts_order_outcomes_notification_failures_and_dlq():
    text = (OBSERVE / "dashboard.tf").read_text()
    for metric in ("OrdersPaid", "OrdersCancelled", "OrdersRejected", "LatePayments"):
        assert metric in text
        assert metric in WORKER.read_text(), f"{metric} producer missing"
    for needle in (
        '"ChopeE"',
        "service",
        "order_worker",
        "NumberOfNotificationsFailed",
        "order_events_topic",
        "notify_dlq_name",
        "WebhookSignatureFailures",
    ):
        assert needle in text, needle


def test_dashboard_labels_the_healthy_hosts_proxy():
    text = (OBSERVE / "dashboard.tf").read_text()
    assert "Fargate CPU and healthy hosts (health proxy)" in text


def test_functions_export_the_dashboard_metric_namespace():
    text = (ROOT / "infra" / "terraform" / "modules" / "functions" / "main.tf").read_text()
    assert 'POWERTOOLS_METRICS_NAMESPACE = "ChopeE"' in text


def test_all_alarms_have_actions_and_thresholds():
    parsed = parse("alarms.tf")
    alarms = resource_blocks(parsed, "aws_cloudwatch_metric_alarm")
    assert len(alarms) == 13
    for name, body in alarms.items():
        assert "alarm_actions" in body, name
        assert "ok_actions" in body, name
        assert "evaluation_periods" in body, name
        assert "threshold" in body, name
        assert body["alarm_actions"] == "${local.actions}", name
        assert body["ok_actions"] == "${local.actions}", name
    assert parsed["locals"][0]["actions"] == ["${var.ops_topic_arn}"]


def test_alarm_names_are_unique_and_prefixed():
    parsed = parse("alarms.tf")
    alarms = resource_blocks(parsed, "aws_cloudwatch_metric_alarm")
    names = [body["alarm_name"] for body in alarms.values()]
    assert len(names) == len(set(names))
    # Dynamic names resolve to chopee-* function names at plan time.
    assert all(
        "chopee" in name or "${each.value}" in name or "${var.worker_function_name}" in name
        for name in names
    )


def test_sns_and_dlq_alarms_target_the_expected_dimensions():
    parsed = parse("alarms.tf")
    alarms = resource_blocks(parsed, "aws_cloudwatch_metric_alarm")
    sns = alarms['"sns_failed"']
    assert sns["namespace"] == '"AWS/SNS"'
    assert sns["metric_name"] == '"NumberOfNotificationsFailed"'
    assert sns["dimensions"] == {"TopicName": "${var.order_events_topic}"}
    dlq = alarms['"dlq_visible"']
    assert dlq["namespace"] == '"AWS/SQS"'
    assert dlq["metric_name"] == '"ApproximateNumberOfMessagesVisible"'
    assert dlq["dimensions"] == {"QueueName": "${each.value}"}
