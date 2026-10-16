output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "alb_arn_suffix" {
  value = aws_lb.this.arn_suffix
}

output "checkout_tg_arn_suffix" {
  value = aws_lb_target_group.svc["checkout"].arn_suffix
}

output "catalog_cart_tg_arn_suffix" {
  value = aws_lb_target_group.svc["catalog_cart"].arn_suffix
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "checkout_service_name" {
  value = aws_ecs_service.svc["checkout"].name
}

output "catalog_cart_service_name" {
  value = aws_ecs_service.svc["catalog_cart"].name
}

output "checkout_log_group_name" {
  value = aws_cloudwatch_log_group.svc["checkout"].name
}
