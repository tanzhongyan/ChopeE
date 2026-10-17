output "pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "pool_arn" {
  value = aws_cognito_user_pool.this.arn
}

output "client_id" {
  value = aws_cognito_user_pool_client.web.id
}
