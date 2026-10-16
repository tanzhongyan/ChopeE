locals {
  repo_root = abspath("${path.root}/../..")
}

module "network" {
  source = "./modules/network"
}

module "registry" {
  source = "./modules/registry"
}

module "data" {
  source = "./modules/data"
}

module "queues" {
  source = "./modules/queues"
}

module "identity" {
  source = "./modules/identity"
}

module "events" {
  source = "./modules/events"

  alert_email = var.alert_email
}

module "compute" {
  source = "./modules/compute"

  vpc_id               = module.network.vpc_id
  subnet_ids           = module.network.subnet_ids
  operator_cidr        = var.operator_cidr
  repo_urls            = module.registry.repo_urls
  image_tag            = var.image_tag
  table_name           = module.data.table_name
  table_arn            = module.data.table_arn
  orders_queue_url     = module.queues.orders_url
  orders_queue_arn     = module.queues.orders_arn
  user_pool_id         = module.identity.pool_id
  client_id            = module.identity.client_id
  ssm_parameter_arns   = module.data.ssm_parameter_arns
  webhook_secret_arn   = module.data.webhook_secret_arn
  log_salt_arn         = module.data.log_salt_arn
  origin_verify_value  = module.data.origin_verify_value
  checkout_min_tasks   = var.checkout_min_tasks
  checkout_burst_tasks = var.checkout_burst_tasks
  prescale_at          = var.prescale_at
}

module "functions" {
  source = "./modules/functions"

  repo_root                   = local.repo_root
  table_name                  = module.data.table_name
  table_arn                   = module.data.table_arn
  stream_arn                  = module.data.stream_arn
  orders_queue_arn            = module.queues.orders_arn
  notify_dlq_arn              = module.queues.notify_dlq_arn
  notify_dlq_url              = module.queues.notify_dlq_url
  order_events_topic_arn      = module.events.order_events_topic_arn
  log_salt_arn                = module.data.log_salt_arn
  expiry_minutes              = var.expiry_minutes
  worker_reserved_concurrency = var.worker_reserved_concurrency
  powertools_layer_arn        = var.powertools_layer_arn
  reports_bucket_name         = module.data.reports_bucket_name
  reports_bucket_arn          = module.data.reports_bucket_arn
  report_log_groups           = [module.compute.checkout_log_group_name, "/aws/lambda/chopee-order-worker"]
}

module "edge" {
  source = "./modules/edge"

  repo_root           = local.repo_root
  alb_dns_name        = module.compute.alb_dns_name
  origin_verify_value = module.data.origin_verify_value
  region              = "ap-southeast-1"
  user_pool_id        = module.identity.pool_id
  client_id           = module.identity.client_id
}

module "observe" {
  source = "./modules/observe"

  ops_topic_arn          = module.events.ops_topic_arn
  order_events_topic     = module.events.order_events_topic_name
  alb_arn_suffix         = module.compute.alb_arn_suffix
  checkout_tg_suffix     = module.compute.checkout_tg_arn_suffix
  catalog_tg_suffix      = module.compute.catalog_cart_tg_arn_suffix
  cluster_name           = module.compute.cluster_name
  checkout_service_name  = module.compute.checkout_service_name
  catalog_service_name   = module.compute.catalog_cart_service_name
  checkout_min_tasks     = var.checkout_min_tasks
  orders_queue_name      = module.queues.orders_name
  orders_dlq_name        = module.queues.dlq_name
  notify_dlq_name        = module.queues.notify_dlq_name
  worker_function_name   = module.functions.worker_function_name
  relay_function_name    = module.functions.relay_function_name
  function_names         = module.functions.function_names
  table_name             = module.data.table_name
  worker_timeout_seconds = module.functions.worker_timeout_seconds
}
