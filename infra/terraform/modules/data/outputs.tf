output "table_name" {
  value = aws_dynamodb_table.chopee.name
}

output "table_arn" {
  value = aws_dynamodb_table.chopee.arn
}

output "stream_arn" {
  value = aws_dynamodb_table.chopee.stream_arn
}

output "webhook_secret_arn" {
  value = aws_ssm_parameter.webhook_secret.arn
}

output "webhook_secret_name" {
  value = aws_ssm_parameter.webhook_secret.name
}

output "log_salt_arn" {
  value = aws_ssm_parameter.log_salt.arn
}

output "ssm_parameter_arns" {
  value = [
    aws_ssm_parameter.webhook_secret.arn,
    aws_ssm_parameter.log_salt.arn,
  ]
}

output "origin_verify_value" {
  value     = random_password.origin_verify.result
  sensitive = true
}

output "reports_bucket_name" {
  value = aws_s3_bucket.reports.bucket
}

output "reports_bucket_arn" {
  value = aws_s3_bucket.reports.arn
}
