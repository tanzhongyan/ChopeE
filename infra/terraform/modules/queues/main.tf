# Plan 06 Section 5.3.

resource "aws_sqs_queue" "orders_dlq" {
  name                        = "chopee-orders-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 14 * 24 * 3600
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "orders" {
  name                        = "chopee-orders.fifo"
  fifo_queue                  = true
  content_based_deduplication = true # required by EventBridge Scheduler FIFO targets
  deduplication_scope         = "messageGroup"
  fifo_throughput_limit       = "perMessageGroupId"
  visibility_timeout_seconds  = 180 # 6 x 30 s worker timeout
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.orders_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "orders_dlq" {
  queue_url = aws_sqs_queue.orders_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.orders.arn]
  })
}

resource "aws_sqs_queue" "notify_dlq" {
  name                      = "chopee-notify-dlq"
  message_retention_seconds = 14 * 24 * 3600
  sqs_managed_sse_enabled   = true
}
