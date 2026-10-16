# Plan 04 demo alarm set. Idle event-driven metrics treat missing data as not breaching.

locals {
  actions = [var.ops_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx_rate" {
  alarm_name          = "chopee-alb-5xx-rate"
  alarm_description   = "Target 5XX share of requests above 2% over five minutes"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 2
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions

  metric_query {
    id          = "rate"
    expression  = "100 * errors / MAX([errors, requests])"
    label       = "5XX %"
    return_data = true
  }

  metric_query {
    id = "errors"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_Target_5XX_Count"
      period      = 300
      stat        = "Sum"
      dimensions  = { LoadBalancer = var.alb_arn_suffix }
    }
  }

  metric_query {
    id = "requests"
    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      period      = 300
      stat        = "Sum"
      dimensions  = { LoadBalancer = var.alb_arn_suffix }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "checkout_latency" {
  alarm_name          = "chopee-checkout-latency-p95"
  alarm_description   = "Checkout target response time p95 above 200 ms for three one-minute periods"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.checkout_tg_suffix }
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  threshold           = 0.2
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "fargate_cpu" {
  for_each = {
    checkout     = var.checkout_service_name
    catalog_cart = var.catalog_service_name
  }

  alarm_name          = "chopee-${replace(each.key, "_", "-")}-cpu-high"
  alarm_description   = "Service CPU above 70% for three one-minute periods"
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  dimensions          = { ClusterName = var.cluster_name, ServiceName = each.value }
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 3
  threshold           = 70
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "checkout_healthy_hosts" {
  alarm_name          = "chopee-checkout-healthy-hosts-low"
  alarm_description   = "Healthy checkout targets below the minimum task count for three periods"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HealthyHostCount"
  dimensions          = { LoadBalancer = var.alb_arn_suffix, TargetGroup = var.checkout_tg_suffix }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  threshold           = var.checkout_min_tasks
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "queue_age" {
  alarm_name          = "chopee-orders-queue-age"
  alarm_description   = "Oldest order message older than 60 s for two periods"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = var.orders_queue_name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 60
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "dlq_visible" {
  for_each = {
    orders = var.orders_dlq_name
    notify = var.notify_dlq_name
  }

  alarm_name          = "chopee-${each.key}-dlq-visible"
  alarm_description   = "Any message visible in the ${each.key} DLQ"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = toset(var.function_names)

  alarm_name          = "${each.value}-errors"
  alarm_description   = "Lambda errors for two consecutive periods"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.value }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "worker_throttles" {
  alarm_name          = "${var.worker_function_name}-throttles"
  alarm_description   = "Worker throttled for two consecutive periods"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = var.worker_function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "worker_duration" {
  alarm_name          = "${var.worker_function_name}-duration-p95"
  alarm_description   = "Worker duration p95 above 80% of timeout for three periods"
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  dimensions          = { FunctionName = var.worker_function_name }
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 3
  threshold           = var.worker_timeout_seconds * 1000 * 0.8
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "ddb_throttles" {
  alarm_name          = "chopee-ddb-throttles"
  alarm_description   = "Read or write throttle events for two consecutive periods"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  evaluation_periods  = 2
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions

  metric_query {
    id          = "total"
    expression  = "reads + writes"
    label       = "Throttle events"
    return_data = true
  }

  metric_query {
    id = "reads"
    metric {
      namespace   = "AWS/DynamoDB"
      metric_name = "ReadThrottleEvents"
      period      = 60
      stat        = "Sum"
      dimensions  = { TableName = var.table_name }
    }
  }

  metric_query {
    id = "writes"
    metric {
      namespace   = "AWS/DynamoDB"
      metric_name = "WriteThrottleEvents"
      period      = 60
      stat        = "Sum"
      dimensions  = { TableName = var.table_name }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "relay_iterator_age" {
  alarm_name          = "chopee-outbox-relay-iterator-age"
  alarm_description   = "Stream iterator age above 60 s for two periods"
  namespace           = "AWS/Lambda"
  metric_name         = "IteratorAge"
  dimensions          = { FunctionName = var.relay_function_name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 60000
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}

resource "aws_cloudwatch_metric_alarm" "sns_failed" {
  alarm_name          = "chopee-order-events-failed"
  alarm_description   = "Any failed SNS notification in one period"
  namespace           = "AWS/SNS"
  metric_name         = "NumberOfNotificationsFailed"
  dimensions          = { TopicName = var.order_events_topic }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.actions
  ok_actions          = local.actions
}
