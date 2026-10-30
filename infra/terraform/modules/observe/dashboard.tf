data "aws_region" "current" {}

locals {
  region = data.aws_region.current.name
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = "chopee"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "ALB requests and 5XX"
          region = local.region
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", var.alb_arn_suffix],
            [".", "HTTPCode_Target_5XX_Count", ".", "."],
            [".", "HTTPCode_Target_4XX_Count", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Checkout response time"
          region = local.region
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.checkout_tg_suffix, { stat = "p50" }],
            ["...", { stat = "p95" }],
            ["...", { stat = "p99" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "Fargate CPU and healthy hosts (health proxy)"
          region = local.region
          period = 60
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", var.cluster_name, "ServiceName", var.checkout_service_name, { stat = "Average" }],
            ["...", var.catalog_service_name, { stat = "Average" }],
            ["AWS/ApplicationELB", "HealthyHostCount", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.checkout_tg_suffix, { stat = "Minimum", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "Order queue and DLQ"
          region = local.region
          period = 60
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.orders_queue_name, { stat = "Maximum" }],
            [".", "ApproximateNumberOfMessagesNotVisible", ".", ".", { stat = "Maximum" }],
            [".", "ApproximateAgeOfOldestMessage", ".", ".", { stat = "Maximum", yAxis = "right" }],
            [".", "ApproximateNumberOfMessagesVisible", "QueueName", var.orders_dlq_name, { stat = "Maximum" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 12, width = 12, height = 6
        properties = {
          title  = "Order worker"
          region = local.region
          period = 60
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.worker_function_name, { stat = "Sum" }],
            [".", "Errors", ".", ".", { stat = "Sum" }],
            [".", "Throttles", ".", ".", { stat = "Sum" }],
            [".", "ConcurrentExecutions", ".", ".", { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 12, width = 12, height = 6
        properties = {
          title  = "DynamoDB throttles and outbox relay lag"
          region = local.region
          period = 60
          metrics = [
            ["AWS/DynamoDB", "WriteThrottleEvents", "TableName", var.table_name, { stat = "Sum" }],
            [".", "ReadThrottleEvents", ".", ".", { stat = "Sum" }],
            ["AWS/Lambda", "IteratorAge", "FunctionName", var.relay_function_name, { stat = "Maximum", yAxis = "right" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 18, width = 12, height = 6
        properties = {
          title  = "Order outcomes (EMF, service=order_worker)"
          region = local.region
          period = 60
          stat   = "Sum"
          metrics = [
            ["ChopeE", "OrdersPaid", "service", "order_worker"],
            [".", "OrdersCancelled", ".", "."],
            [".", "OrdersRejected", ".", "."],
            [".", "LatePayments", ".", "."],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 18, width = 12, height = 6
        properties = {
          title  = "Notification failures and DLQ"
          region = local.region
          period = 60
          metrics = [
            ["AWS/SNS", "NumberOfNotificationsFailed", "TopicName", var.order_events_topic, { stat = "Sum" }],
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.notify_dlq_name, { stat = "Maximum" }],
            ["chopee", "WebhookSignatureFailures", "service", "checkout", { stat = "Sum" }],
          ]
        }
      },
    ]
  })
}
