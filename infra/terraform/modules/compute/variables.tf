variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "operator_cidr" {
  type = string
}

variable "repo_urls" {
  type = map(string)
}

variable "image_tag" {
  type = string
}

variable "table_name" {
  type = string
}

variable "table_arn" {
  type = string
}

variable "orders_queue_url" {
  type = string
}

variable "orders_queue_arn" {
  type = string
}

variable "user_pool_id" {
  type = string
}

variable "client_id" {
  type = string
}

variable "ssm_parameter_arns" {
  type        = list(string)
  description = "Parameters the task execution role may read to inject secrets."
}

variable "webhook_secret_arn" {
  type = string
}

variable "log_salt_arn" {
  type = string
}

variable "origin_verify_value" {
  type      = string
  sensitive = true
}

variable "checkout_min_tasks" {
  type = number
}

variable "checkout_burst_tasks" {
  type = number
}

variable "prescale_at" {
  type    = string
  default = null
}
