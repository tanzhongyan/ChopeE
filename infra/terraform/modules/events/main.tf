# Topics only. The two filtered order-event subscriptions are created in the
# `functions` module next to the Lambdas they target.

variable "alert_email" {
  type = string
}

resource "aws_sns_topic" "order_events" {
  name = "chopee-order-events"
}

resource "aws_sns_topic" "ops_alerts" {
  name = "chopee-ops-alerts"
}

resource "aws_sns_topic_subscription" "ops_email" {
  topic_arn = aws_sns_topic.ops_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# CloudWatch alarms publish to the ops topic.
data "aws_iam_policy_document" "ops_topic" {
  statement {
    sid       = "AllowCloudWatchAlarms"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.ops_alerts.arn]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
  }
}

resource "aws_sns_topic_policy" "ops_alerts" {
  arn    = aws_sns_topic.ops_alerts.arn
  policy = data.aws_iam_policy_document.ops_topic.json
}
