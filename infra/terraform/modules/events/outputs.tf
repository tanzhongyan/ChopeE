output "order_events_topic_arn" {
  value = aws_sns_topic.order_events.arn
}

output "order_events_topic_name" {
  value = aws_sns_topic.order_events.name
}

output "ops_topic_arn" {
  value = aws_sns_topic.ops_alerts.arn
}
