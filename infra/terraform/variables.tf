variable "run_id" {
  type        = string
  description = "Identifier for this timed run, used in the Run tag."
}

variable "owner" {
  type        = string
  description = "Short owner name for the Owner tag."
}

variable "alert_email" {
  type        = string
  description = "Receives ops alarm notifications. The subscription must be confirmed after every apply."
}

variable "operator_cidr" {
  type        = string
  description = "Operator public IP as a /32 (changes per session). Allowed to reach the ALB directly."

  validation {
    condition     = can(cidrnetmask(var.operator_cidr)) && endswith(var.operator_cidr, "/32")
    error_message = "operator_cidr must be a single IPv4 address in /32 form, for example 203.0.113.7/32."
  }
}

variable "expiry_minutes" {
  type        = number
  default     = 15
  description = "Minutes before an unpaid order expires. Label any shortened value in evidence."
}

variable "worker_reserved_concurrency" {
  type        = number
  default     = 100
  description = "Reserved concurrency for the order worker (plan 02 capacity check)."
}

variable "checkout_min_tasks" {
  type    = number
  default = 2
}

variable "checkout_burst_tasks" {
  type    = number
  default = 6
}

variable "prescale_at" {
  type        = string
  default     = null
  description = "Optional RFC 3339 UTC time (for example 2026-10-20T08:00:00Z) at which checkout min capacity rises to checkout_burst_tasks."
}

variable "image_tag" {
  type        = string
  default     = "demo"
  description = "Tag pushed by scripts/push_images.sh for both service images."
}

variable "powertools_layer_arn" {
  type        = string
  description = "Full ARN (with version) of the AWS Lambda Powertools Python v3 python3.12 arm64 layer in ap-southeast-1."
}
