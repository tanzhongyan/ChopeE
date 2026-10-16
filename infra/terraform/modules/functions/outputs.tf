output "worker_function_name" {
  value = aws_lambda_function.fn["order_worker"].function_name
}

output "relay_function_name" {
  value = aws_lambda_function.fn["outbox_relay"].function_name
}

output "function_names" {
  value = [for f in aws_lambda_function.fn : f.function_name]
}

output "worker_timeout_seconds" {
  value = local.worker_timeout
}

output "expiry_schedule_group" {
  value = aws_scheduler_schedule_group.expiry.name
}
