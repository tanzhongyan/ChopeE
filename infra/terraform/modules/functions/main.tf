data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  names = {
    order_worker     = "chopee-order-worker"
    outbox_relay     = "chopee-outbox-relay"
    notify_logistics = "chopee-notify-logistics"
    notify_customer  = "chopee-notify-customer"
    report           = "chopee-report"
  }

  worker_timeout = 30

  # Names the report Lambda scopes Logs Insights permissions to.
  log_group_arns = [for g in var.report_log_groups : "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:${g}:*"]
}

# ---------------------------------------------------------------- packaging

data "archive_file" "shared_layer" {
  type        = "zip"
  source_dir  = "${var.repo_root}/shared" # contains python/chopee/, the layer layout
  output_path = "${var.repo_root}/build/layers/chopee-shared.zip"
  excludes    = ["**/__pycache__/*", "**/*.pyc"]
}

resource "aws_lambda_layer_version" "shared" {
  layer_name               = "chopee-shared"
  filename                 = data.archive_file.shared_layer.output_path
  source_code_hash         = data.archive_file.shared_layer.output_base64sha256
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["arm64"]
}

data "archive_file" "fn" {
  for_each = local.names

  type        = "zip"
  source_dir  = "${var.repo_root}/functions/${each.key}"
  output_path = "${var.repo_root}/build/functions/${each.key}.zip"
  excludes    = ["**/__pycache__/*", "**/*.pyc"]
}

# Log groups exist before the functions so retention is 1 day from the start.
resource "aws_cloudwatch_log_group" "fn" {
  for_each = local.names

  name              = "/aws/lambda/${each.value}"
  retention_in_days = 1
}

# ---------------------------------------------------------------- IAM

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each = local.names

  name               = "${each.value}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "fn_common" {
  for_each = local.names

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fn[each.key].arn}:*"]
  }

  statement {
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "fn_common" {
  for_each = local.names

  name   = "common"
  role   = aws_iam_role.fn[each.key].id
  policy = data.aws_iam_policy_document.fn_common[each.key].json
}

# order_worker
resource "aws_iam_role" "scheduler" {
  name = "chopee-scheduler-target"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } }
    }]
  })
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [var.orders_queue_arn]
  }

  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.fn["report"].arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "send-to-orders-and-report"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

data "aws_iam_policy_document" "worker" {
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
      "dynamodb:TransactWriteItems",
    ]
    resources = [var.table_arn, "${var.table_arn}/index/GSI1"]
  }

  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [var.orders_queue_arn]
  }

  statement {
    actions   = ["scheduler:CreateSchedule", "scheduler:GetSchedule"]
    resources = ["arn:aws:scheduler:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:schedule/${aws_scheduler_schedule_group.expiry.name}/*"]
  }

  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.scheduler.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["scheduler.amazonaws.com"]
    }
  }

  statement {
    actions   = ["ssm:GetParameter"]
    resources = [var.log_salt_arn]
  }
}

resource "aws_iam_role_policy" "worker" {
  name   = "worker"
  role   = aws_iam_role.fn["order_worker"].id
  policy = data.aws_iam_policy_document.worker.json
}

# outbox_relay
data "aws_iam_policy_document" "relay" {
  statement {
    actions   = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"]
    resources = [var.stream_arn]
  }

  statement {
    actions   = ["sns:Publish"]
    resources = [var.order_events_topic_arn]
  }

  statement {
    actions   = ["sqs:SendMessage"]
    resources = [var.notify_dlq_arn]
  }
}

resource "aws_iam_role_policy" "relay" {
  name   = "relay"
  role   = aws_iam_role.fn["outbox_relay"].id
  policy = data.aws_iam_policy_document.relay.json
}

# notify_* consumers: dedupe item plus async on-failure destination.
data "aws_iam_policy_document" "consumer" {
  statement {
    actions   = ["dynamodb:PutItem"]
    resources = [var.table_arn]
  }

  statement {
    actions   = ["sqs:SendMessage"]
    resources = [var.notify_dlq_arn]
  }
}

resource "aws_iam_role_policy" "consumer" {
  for_each = toset(["notify_logistics", "notify_customer"])

  name   = "consumer"
  role   = aws_iam_role.fn[each.key].id
  policy = data.aws_iam_policy_document.consumer.json
}

# report
data "aws_iam_policy_document" "report" {
  statement {
    actions   = ["logs:StartQuery"]
    resources = local.log_group_arns
  }

  statement {
    actions   = ["logs:GetQueryResults", "logs:StopQuery"]
    resources = ["*"]
  }

  statement {
    actions   = ["s3:PutObject"]
    resources = ["${var.reports_bucket_arn}/reports/*"]
  }
}

resource "aws_iam_role_policy" "report" {
  name   = "report"
  role   = aws_iam_role.fn["report"].id
  policy = data.aws_iam_policy_document.report.json
}

# ---------------------------------------------------------------- functions

locals {
  fn_env = {
    order_worker = {
      TABLE_NAME       = var.table_name
      EXPIRY_MINUTES   = tostring(var.expiry_minutes)
      SCHEDULE_GROUP   = "chopee-expiry"
      SCHEDULER_ROLE   = aws_iam_role.scheduler.arn
      ORDERS_QUEUE_ARN = var.orders_queue_arn
      LOG_SALT_PARAM   = "/chopee/log-salt"
    }
    outbox_relay = {
      TOPIC_ARN = var.order_events_topic_arn
    }
    notify_logistics = {
      TABLE_NAME = var.table_name
    }
    notify_customer = {
      TABLE_NAME = var.table_name
    }
    report = {
      REPORTS_BUCKET = var.reports_bucket_name
      LOG_GROUPS     = join(",", var.report_log_groups)
    }
  }

  fn_timeout = {
    order_worker     = local.worker_timeout
    outbox_relay     = 60
    notify_logistics = 15
    notify_customer  = 15
    report           = 120
  }

  fn_memory = {
    order_worker     = 256
    outbox_relay     = 256
    notify_logistics = 128
    notify_customer  = 128
    report           = 256
  }
}

resource "aws_lambda_function" "fn" {
  for_each = local.names

  function_name    = each.value
  role             = aws_iam_role.fn[each.key].arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.fn[each.key].output_path
  source_code_hash = data.archive_file.fn[each.key].output_base64sha256
  timeout          = local.fn_timeout[each.key]
  memory_size      = local.fn_memory[each.key]
  layers           = [aws_lambda_layer_version.shared.arn, var.powertools_layer_arn]

  reserved_concurrent_executions = each.key == "order_worker" ? var.worker_reserved_concurrency : -1

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(
      {
        POWERTOOLS_SERVICE_NAME      = each.value
        POWERTOOLS_METRICS_NAMESPACE = "ChopeE"
        LOG_LEVEL                    = "INFO"
      },
      local.fn_env[each.key],
    )
  }

  depends_on = [aws_cloudwatch_log_group.fn, aws_iam_role_policy.fn_common]
}

# ---------------------------------------------------------------- triggers

resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn        = var.orders_queue_arn
  function_name           = aws_lambda_function.fn["order_worker"].arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]

  dynamic "scaling_config" {
    for_each = var.worker_max_concurrency == null ? [] : [var.worker_max_concurrency]
    content {
      maximum_concurrency = scaling_config.value
    }
  }

  depends_on = [aws_iam_role_policy.worker]
}

resource "aws_lambda_event_source_mapping" "relay" {
  event_source_arn                   = var.stream_arn
  function_name                      = aws_lambda_function.fn["outbox_relay"].arn
  starting_position                  = "LATEST"
  batch_size                         = 100
  maximum_batching_window_in_seconds = 1
  maximum_retry_attempts             = 5
  bisect_batch_on_function_error     = true
  function_response_types            = ["ReportBatchItemFailures"]

  depends_on = [aws_iam_role_policy.relay]

  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["INSERT"]
        dynamodb  = { Keys = { PK = { S = [{ prefix = "EVENT#" }] } } }
      })
    }
  }

  destination_config {
    on_failure {
      destination_arn = var.notify_dlq_arn
    }
  }
}

# ---------------------------------------------------------------- SNS subscribers

locals {
  subscriptions = {
    notify_logistics = ["OrderPaid"]
    notify_customer  = ["OrderPendingPayment", "OrderPaid", "OrderCancelled", "OrderRejected"]
  }
}

resource "aws_sns_topic_subscription" "consumer" {
  for_each = local.subscriptions

  topic_arn     = var.order_events_topic_arn
  protocol      = "lambda"
  endpoint      = aws_lambda_function.fn[each.key].arn
  filter_policy = jsonencode({ eventType = each.value })

  redrive_policy = jsonencode({
    deadLetterTargetArn = var.notify_dlq_arn
  })
}

resource "aws_lambda_permission" "sns" {
  for_each = local.subscriptions

  statement_id  = "AllowSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.key].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = var.order_events_topic_arn
}

data "aws_iam_policy_document" "notify_dlq" {
  statement {
    sid       = "AllowSnsRedrive"
    actions   = ["sqs:SendMessage"]
    resources = [var.notify_dlq_arn]

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [var.order_events_topic_arn]
    }
  }
}

resource "aws_sqs_queue_policy" "notify_dlq" {
  queue_url = var.notify_dlq_url
  policy    = data.aws_iam_policy_document.notify_dlq.json
}

resource "aws_lambda_function_event_invoke_config" "consumer" {
  for_each = local.subscriptions

  function_name = aws_lambda_function.fn[each.key].function_name

  destination_config {
    on_failure {
      destination = var.notify_dlq_arn
    }
  }
}

# ---------------------------------------------------------------- Scheduler

resource "aws_scheduler_schedule_group" "expiry" {
  name = "chopee-expiry"
}

resource "aws_scheduler_schedule" "report" {
  name                = "chopee-report-daily"
  schedule_expression = "cron(0 19 * * ? *)" # 03:00 SGT
  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.fn["report"].arn
    role_arn = aws_iam_role.scheduler.arn
  }
}
