resource "aws_cognito_user_pool" "this" {
  name           = "chopee-users"
  user_pool_tier = "LITE"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  deletion_protection = "INACTIVE"
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "chopee-web"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Long enough that pre-minted load-test tokens outlive the run.
  access_token_validity  = 3
  id_token_validity      = 3
  refresh_token_validity = 1

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  prevent_user_existence_errors = "ENABLED"
}
