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


def unquote(value: str) -> str:
    return value.strip('"') if isinstance(value, str) else value


def dashboard_widgets() -> list[dict]:
    parsed = parse("dashboard.tf")
    body = resource_blocks(parsed, "aws_cloudwatch_dashboard")['"this"']["dashboard_body"]
    match = re.match(r"^\$\{jsonencode\((.*)\)\}$", body, re.S)
    assert match, "dashboard_body must be a jsonencode object"
    return hcl2.loads("x = " + match.group(1))["x"]["widgets"]


def test_dashboard_parses_and_has_expected_widgets():
    parsed = parse("dashboard.tf")
    dashboards = resource_blocks(parsed, "aws_cloudwatch_dashboard")
    assert list(dashboards) == ['"this"']
    assert dashboards['"this"']["dashboard_name"] == '"chopee"'
    widgets = dashboard_widgets()
    assert len(widgets) == 8
    assert all(w["type"] == '"metric"' for w in widgets)
    titles = [unquote(w["properties"]["title"]) for w in widgets]
    assert len(titles) == len(set(titles))


def test_dashboard_charts_order_outcomes_with_the_correct_namespace():
    widgets = dashboard_widgets()
    widget = next(w for w in widgets if "Order outcomes" in unquote(w["properties"]["title"]))
    rows = widget["properties"]["metrics"]
    assert widget["properties"]["stat"] == '"Sum"'
    assert [unquote(v) for v in rows[0][:4]] == ["ChopeE", "OrdersPaid", "service", "order_worker"]
    assert [unquote(row[1]) for row in rows[:4]] == [
        "OrdersPaid", "OrdersCancelled", "OrdersRejected", "LatePayments"
    ]
    source = WORKER.read_text()
    for metric in ("OrdersPaid", "OrdersCancelled", "OrdersRejected", "LatePayments"):
        assert f'"{metric}"' in source, f"{metric} producer missing"


def test_dashboard_charts_notification_failures_and_both_dlqs():
    widgets = dashboard_widgets()
    widget = next(w for w in widgets if "Notification" in unquote(w["properties"]["title"]))
    rows = widget["properties"]["metrics"]
    assert [unquote(v) for v in rows[0][:5] if isinstance(v, str)] == [
        "AWS/SNS", "NumberOfNotificationsFailed", "TopicName", "${var.order_events_topic}"
    ]
    assert [unquote(v) for v in rows[1][:4]] == [
        "AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", "${var.notify_dlq_name}"
    ]
    assert [unquote(v) for v in rows[2][:5] if isinstance(v, str)] == [
        "chopee", "WebhookSignatureFailures", "service", "checkout"
    ]


def test_order_queue_widget_covers_the_orders_queue_and_dlq():
    widgets = dashboard_widgets()
    widget = next(w for w in widgets if "Order queue and DLQ" in unquote(w["properties"]["title"]))
    rows = widget["properties"]["metrics"]
    assert [unquote(rows[0][i]) for i in (0, 1, 2, 3)] == [
        "AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", "${var.orders_queue_name}"
    ]
    assert [unquote(rows[3][i]) for i in (0, 1, 2, 3)] == [
        ".", "ApproximateNumberOfMessagesVisible", "QueueName", "${var.orders_dlq_name}"
    ]
    assert rows[0][4]["stat"] == '"Maximum"' and rows[3][4]["stat"] == '"Maximum"'


def test_dashboard_labels_the_healthy_hosts_proxy():
    widgets = dashboard_widgets()
    titles = [unquote(w["properties"]["title"]) for w in widgets]
    assert "Fargate CPU and healthy hosts (health proxy)" in titles


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
