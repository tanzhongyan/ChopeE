terraform {
  required_version = ">= 1.5"

  required_providers {
    # user_pool_tier on aws_cognito_user_pool needs a 5.x release that includes it.
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.80, < 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}
