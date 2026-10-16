# One-time AWS Budget guard (plan 06 Section 6.3). Applied once and kept; not part of teardown.
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "ap-southeast-1"
  default_tags {
    tags = {
      Project = "chopee"
      Owner   = var.owner
    }
  }
}

variable "alert_email" {
  type        = string
  description = "Address that receives budget notices."
}

variable "owner" {
  type        = string
  description = "Short owner name for tags."
}

variable "limit_usd" {
  type    = string
  default = "80"
}

variable "start_date" {
  type        = string
  description = "Budget start, first day of a month, format YYYY-MM-DD_00:00."
}

resource "aws_budgets_budget" "chopee" {
  name              = "chopee-project-cap"
  budget_type       = "COST"
  limit_amount      = var.limit_usd
  limit_unit        = "USD"
  time_unit         = "ANNUALLY"
  time_period_start = var.start_date

  dynamic "notification" {
    for_each = [
      { threshold = 50, type = "ACTUAL" },
      { threshold = 80, type = "ACTUAL" },
      { threshold = 100, type = "ACTUAL" },
      { threshold = 100, type = "FORECASTED" },
    ]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value.type
      subscriber_email_addresses = [var.alert_email]
    }
  }
}
