# DynamoDB table (plan 06 Section 5.1), SSM secrets and the reports bucket.
# Secrets and the reports bucket live here, not in `observe`, so that compute,
# functions and observe can all consume them without a module-level cycle.

resource "aws_dynamodb_table" "chopee" {
  name         = "chopee"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  point_in_time_recovery {
    enabled = true
  }

  # The demo stack is destroyed after every run.
  deletion_protection_enabled = false
}

resource "random_password" "webhook_secret" {
  length  = 40
  special = false
}

resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

resource "random_password" "log_salt" {
  length  = 32
  special = false
}

resource "aws_ssm_parameter" "webhook_secret" {
  name  = "/chopee/webhook-secret"
  type  = "SecureString"
  value = random_password.webhook_secret.result
}

resource "aws_ssm_parameter" "origin_verify" {
  name  = "/chopee/origin-verify"
  type  = "SecureString"
  value = random_password.origin_verify.result
}

resource "aws_ssm_parameter" "log_salt" {
  name  = "/chopee/log-salt"
  type  = "SecureString"
  value = random_password.log_salt.result
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "reports" {
  bucket        = "chopee-reports-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
