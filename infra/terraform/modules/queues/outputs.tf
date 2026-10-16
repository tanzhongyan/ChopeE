output "orders_url" {
  value = aws_sqs_queue.orders.url
}

output "orders_arn" {
  value = aws_sqs_queue.orders.arn
}

output "orders_name" {
  value = aws_sqs_queue.orders.name
}

output "dlq_url" {
  value = aws_sqs_queue.orders_dlq.url
}

output "dlq_arn" {
  value = aws_sqs_queue.orders_dlq.arn
}

output "dlq_name" {
  value = aws_sqs_queue.orders_dlq.name
}

output "notify_dlq_url" {
  value = aws_sqs_queue.notify_dlq.url
}

output "notify_dlq_arn" {
  value = aws_sqs_queue.notify_dlq.arn
}

output "notify_dlq_name" {
  value = aws_sqs_queue.notify_dlq.name
}
