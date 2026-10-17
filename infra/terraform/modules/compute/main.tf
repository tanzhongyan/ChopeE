data "aws_region" "current" {}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

locals {
  services = {
    catalog_cart = {
      name   = "chopee-catalog-cart"
      cpu    = 512
      memory = 1024
      min    = 2
      paths  = ["/api/catalog*", "/api/cart*"]
      prio   = 10
    }
    checkout = {
      name   = "chopee-checkout"
      cpu    = 1024
      memory = 2048
      min    = var.checkout_min_tasks
      paths  = ["/api/checkout*", "/api/orders*", "/api/demo/*"]
      prio   = 20
    }
  }

  # Uvicorn: 2 workers per vCPU (plan 06 Section 5.2).
  uvicorn_workers = { catalog_cart = 1, checkout = 2 }

  issuer = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${var.user_pool_id}"
}

# ---------------------------------------------------------------- security groups

resource "aws_security_group" "alb" {
  name        = "chopee-alb"
  description = "ALB: CloudFront origin-facing prefix list and the operator only"
  vpc_id      = var.vpc_id
}

# Two rules only: the managed prefix list counts as ~55 entries toward the SG rule quota.
resource "aws_vpc_security_group_ingress_rule" "alb_cloudfront" {
  security_group_id = aws_security_group.alb.id
  description       = "CloudFront origin-facing"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_operator" {
  security_group_id = aws_security_group.alb.id
  description       = "Operator (simulated gateway, k6 debugging)"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = var.operator_cidr
}

resource "aws_vpc_security_group_egress_rule" "alb_all" {
  security_group_id = aws_security_group.alb.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "tasks" {
  name        = "chopee-tasks"
  description = "Fargate tasks: traffic from the ALB only"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = aws_security_group.tasks.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "tasks_all" {
  security_group_id = aws_security_group.tasks.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ---------------------------------------------------------------- ALB

resource "aws_lb" "this" {
  name               = "chopee-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.subnet_ids
}

resource "aws_lb_target_group" "svc" {
  for_each = local.services

  name                 = each.value.name
  port                 = 8080
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 30

  health_check {
    path                = "/api/healthz"
    matcher             = "200"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "application/json"
      message_body = "{\"detail\":\"not found\"}"
      status_code  = "404"
    }
  }
}

# Everything except the payment webhook must carry the CloudFront-injected
# X-Origin-Verify header, so another distribution cannot reach the ALB.
resource "aws_lb_listener_rule" "svc" {
  for_each = local.services

  listener_arn = aws_lb_listener.http.arn
  priority     = each.value.prio

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.svc[each.key].arn
  }

  condition {
    path_pattern {
      values = each.value.paths
    }
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [var.origin_verify_value]
    }
  }
}

# The simulated gateway calls the ALB directly from operator_cidr (no header).
# The webhook is protected by its HMAC signature (plan 06 Section 5.2), and the
# ALB security group already limits who can reach the listener.
resource "aws_lb_listener_rule" "webhook" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 5

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.svc["checkout"].arn
  }

  condition {
    path_pattern {
      values = ["/api/webhooks/*"]
    }
  }
}

# ---------------------------------------------------------------- IAM

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "chopee-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_ssm" {
  statement {
    actions   = ["ssm:GetParameters", "ssm:GetParameter"]
    resources = var.ssm_parameter_arns
  }
}

resource "aws_iam_role_policy" "execution_ssm" {
  name   = "read-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_ssm.json
}

resource "aws_iam_role" "task" {
  for_each = local.services

  name               = "${each.value.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "task" {
  for_each = local.services

  # catalog-cart: product reads plus cart reads/writes, scoped by leading key.
  dynamic "statement" {
    for_each = each.key == "catalog_cart" ? [1] : []

    content {
      actions = [
        "dynamodb:GetItem",
        "dynamodb:BatchGetItem",
        "dynamodb:Query",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:TransactWriteItems",
      ]
      resources = [var.table_arn, "${var.table_arn}/index/GSI1"]

      condition {
        test     = "ForAllValues:StringLike"
        variable = "dynamodb:LeadingKeys"
        values   = ["PRODUCT#*", "CART#*", "CATALOG"]
      }
    }
  }

  # checkout: one GetItem for idempotency / order reads, order history query.
  dynamic "statement" {
    for_each = each.key == "checkout" ? [1] : []

    content {
      actions   = ["dynamodb:GetItem", "dynamodb:Query"]
      resources = [var.table_arn, "${var.table_arn}/index/GSI1"]
    }
  }

  dynamic "statement" {
    for_each = each.key == "checkout" ? [1] : []

    content {
      actions   = ["sqs:SendMessage"]
      resources = [var.orders_queue_arn]
    }
  }

  dynamic "statement" {
    for_each = each.key == "checkout" ? [1] : []

    content {
      actions   = ["ssm:GetParameter"]
      resources = [var.webhook_secret_arn, var.log_salt_arn]
    }
  }

  # X-Ray (sidecar and app SDK).
  statement {
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "task" {
  for_each = local.services

  name   = "access"
  role   = aws_iam_role.task[each.key].id
  policy = data.aws_iam_policy_document.task[each.key].json
}

# ---------------------------------------------------------------- ECS

resource "aws_cloudwatch_log_group" "svc" {
  for_each = local.services

  name              = "/ecs/${each.value.name}"
  retention_in_days = 1
}

resource "aws_ecs_cluster" "this" {
  name = "chopee"
}

locals {
  common_env = [
    { name = "AWS_REGION", value = data.aws_region.current.name },
    { name = "TABLE_NAME", value = var.table_name },
    { name = "USER_POOL_ID", value = var.user_pool_id },
    { name = "COGNITO_CLIENT_ID", value = var.client_id },
    { name = "COGNITO_ISSUER", value = local.issuer },
    { name = "AWS_XRAY_DAEMON_ADDRESS", value = "127.0.0.1:2000" },
  ]

  checkout_env = [
    { name = "QUEUE_URL", value = var.orders_queue_url },
    { name = "DEMO_GATEWAY", value = "true" },
    { name = "WEBHOOK_SECRET_PARAM", value = "/chopee/webhook-secret" },
  ]

  container_secrets = {
    catalog_cart = [
      { name = "LOG_SALT", valueFrom = var.log_salt_arn },
    ]
    checkout = [
      { name = "LOG_SALT", valueFrom = var.log_salt_arn },
      { name = "WEBHOOK_SECRET", valueFrom = var.webhook_secret_arn },
    ]
  }
}

resource "aws_ecs_task_definition" "svc" {
  for_each = local.services

  family                   = each.value.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task[each.key].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode(concat(
    [
      {
        name      = "app"
        image     = "${var.repo_urls[each.key]}:${var.image_tag}"
        essential = true
        portMappings = [
          { containerPort = 8080, protocol = "tcp" }
        ]
        environment = concat(
          local.common_env,
          each.key == "checkout" ? local.checkout_env : [],
          [{ name = "UVICORN_WORKERS", value = tostring(local.uvicorn_workers[each.key]) }],
        )
        secrets = local.container_secrets[each.key]
        logConfiguration = {
          logDriver = "awslogs"
          options = {
            awslogs-group         = aws_cloudwatch_log_group.svc[each.key].name
            awslogs-region        = data.aws_region.current.name
            awslogs-stream-prefix = "app"
          }
        }
      }
    ],
    each.key == "checkout" ? [
      {
        name      = "xray-daemon"
        image     = "public.ecr.aws/xray/aws-xray-daemon:3.x"
        essential = false
        cpu       = 32
        memory    = 256
        portMappings = [
          { containerPort = 2000, protocol = "udp" }
        ]
        logConfiguration = {
          logDriver = "awslogs"
          options = {
            awslogs-group         = aws_cloudwatch_log_group.svc[each.key].name
            awslogs-region        = data.aws_region.current.name
            awslogs-stream-prefix = "xray"
          }
        }
      }
    ] : [],
  ))
}

resource "aws_ecs_service" "svc" {
  for_each = local.services

  name            = each.value.name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.svc[each.key].arn
  desired_count   = each.value.min
  launch_type     = "FARGATE"

  health_check_grace_period_seconds  = 60
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.svc[each.key].arn
    container_name   = "app"
    container_port   = 8080
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [desired_count]
  }

  depends_on = [aws_lb_listener_rule.svc, aws_lb_listener_rule.webhook]
}

# ---------------------------------------------------------------- autoscaling

resource "aws_appautoscaling_target" "svc" {
  for_each = local.services

  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.svc[each.key].name}"
  min_capacity       = each.value.min
  max_capacity       = 10
}

resource "aws_appautoscaling_policy" "cpu" {
  for_each = local.services

  name               = "${each.value.name}-cpu60"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.svc[each.key].service_namespace
  scalable_dimension = aws_appautoscaling_target.svc[each.key].scalable_dimension
  resource_id        = aws_appautoscaling_target.svc[each.key].resource_id

  target_tracking_scaling_policy_configuration {
    target_value = 60

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_scheduled_action" "checkout_prescale" {
  count = var.prescale_at == null ? 0 : 1

  name               = "chopee-checkout-prescale"
  service_namespace  = aws_appautoscaling_target.svc["checkout"].service_namespace
  scalable_dimension = aws_appautoscaling_target.svc["checkout"].scalable_dimension
  resource_id        = aws_appautoscaling_target.svc["checkout"].resource_id
  schedule           = "at(${formatdate("YYYY-MM-DD'T'hh:mm:ss", var.prescale_at)})"
  timezone           = "UTC"

  scalable_target_action {
    min_capacity = var.checkout_burst_tasks
    max_capacity = 10
  }
}
