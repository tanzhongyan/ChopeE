variable "ops_topic_arn" {
  type = string
}

variable "order_events_topic" {
  type = string
}

variable "alb_arn_suffix" {
  type = string
}

variable "checkout_tg_suffix" {
  type = string
}

variable "catalog_tg_suffix" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "checkout_service_name" {
  type = string
}

variable "catalog_service_name" {
  type = string
}

variable "checkout_min_tasks" {
  type = number
}

variable "orders_queue_name" {
  type = string
}

variable "orders_dlq_name" {
  type = string
}

variable "notify_dlq_name" {
  type = string
}

variable "worker_function_name" {
  type = string
}

variable "relay_function_name" {
  type = string
}

variable "function_names" {
  type = list(string)
}

variable "table_name" {
  type = string
}

variable "worker_timeout_seconds" {
  type = number
}
