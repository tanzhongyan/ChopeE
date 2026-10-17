output "cloudfront_url" {
  value = "https://${module.edge.cloudfront_domain}"
}

output "cloudfront_distribution_id" {
  value = module.edge.distribution_id
}

output "alb_dns_name" {
  value = module.compute.alb_dns_name
}

output "user_pool_id" {
  value = module.identity.pool_id
}

output "client_id" {
  value = module.identity.client_id
}

output "queue_url" {
  value = module.queues.orders_url
}

output "dlq_url" {
  value = module.queues.dlq_url
}

output "notify_dlq_url" {
  value = module.queues.notify_dlq_url
}

output "table_name" {
  value = module.data.table_name
}

output "ecr_repos" {
  value = module.registry.repo_urls
}

output "reports_bucket" {
  value = module.data.reports_bucket_name
}

output "ecs_cluster" {
  value = module.compute.cluster_name
}

output "checkout_service" {
  value = module.compute.checkout_service_name
}

output "ops_topic_arn" {
  value = module.events.ops_topic_arn
}

output "webhook_secret_parameter" {
  description = "SSM parameter name; scripts read the value with --with-decryption."
  value       = module.data.webhook_secret_name
}
