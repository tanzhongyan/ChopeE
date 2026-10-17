variable "repo_root" {
  type        = string
  description = "Absolute path to the repository root (contains shared/ and functions/)."
}

variable "table_name" {
  type = string
}

variable "table_arn" {
  type = string
}

variable "stream_arn" {
  type = string
}

variable "orders_queue_arn" {
  type = string
}

variable "notify_dlq_arn" {
  type = string
}

variable "notify_dlq_url" {
  type = string
}

variable "order_events_topic_arn" {
  type = string
}

variable "log_salt_arn" {
  type = string
}

variable "expiry_minutes" {
  type = number
}

variable "worker_reserved_concurrency" {
  type = number
}

variable "worker_max_concurrency" {
  type    = number
  default = null
}

variable "powertools_layer_arn" {
  type = string
}

variable "reports_bucket_name" {
  type = string
}

variable "reports_bucket_arn" {
  type = string
}

variable "report_log_groups" {
  type        = list(string)
  description = "Log groups the report Lambda queries with Logs Insights."
}
