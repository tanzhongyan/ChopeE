variable "repo_root" {
  type = string
}

variable "alb_dns_name" {
  type = string
}

variable "origin_verify_value" {
  type      = string
  sensitive = true
}

variable "region" {
  type = string
}

variable "user_pool_id" {
  type = string
}

variable "client_id" {
  type = string
}

data "aws_caller_identity" "current" {}

locals {
  storefront_dir = "${var.repo_root}/storefront"

  # config.json is rendered here; apiBase is same-origin because /api/* is a CloudFront behaviour.
  config_json = jsonencode({
    apiBase    = "/api"
    region     = var.region
    userPoolId = var.user_pool_id
    clientId   = var.client_id
  })

  content_types = {
    html = "text/html; charset=utf-8"
    js   = "application/javascript; charset=utf-8"
    css  = "text/css; charset=utf-8"
    json = "application/json"
    svg  = "image/svg+xml"
    txt  = "text/plain; charset=utf-8"
  }

  # Files in storefront/ except a hand-written config.json (Terraform renders the real one).
  storefront_files = [for f in fileset(local.storefront_dir, "**") : f if f != "config.json"]

  # AWS managed CloudFront policies.
  caching_optimized                 = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  caching_disabled                  = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  all_viewer_except_host_header_orp = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
}

resource "aws_s3_bucket" "storefront" {
  bucket        = "chopee-storefront-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "storefront" {
  bucket                  = aws_s3_bucket.storefront.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "storefront" {
  for_each = toset(local.storefront_files)

  bucket       = aws_s3_bucket.storefront.id
  key          = each.value
  source       = "${local.storefront_dir}/${each.value}"
  etag         = filemd5("${local.storefront_dir}/${each.value}")
  content_type = lookup(local.content_types, reverse(split(".", each.value))[0], "application/octet-stream")
}

resource "aws_s3_object" "config" {
  bucket       = aws_s3_bucket.storefront.id
  key          = "config.json"
  content      = local.config_json
  content_type = "application/json"
}

resource "aws_cloudfront_origin_access_control" "storefront" {
  name                              = "chopee-storefront"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  comment             = "chopee demo"
  default_root_object = "index.html"
  price_class         = "PriceClass_200"
  http_version        = "http2"

  origin {
    origin_id                = "s3-storefront"
    domain_name              = aws_s3_bucket.storefront.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.storefront.id
  }

  origin {
    origin_id   = "alb-api"
    domain_name = var.alb_dns_name

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = var.origin_verify_value
    }
  }

  default_cache_behavior {
    target_origin_id       = "s3-storefront"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = local.caching_optimized
  }

  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "alb-api"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = local.caching_disabled
    origin_request_policy_id = local.all_viewer_except_host_header_orp
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

data "aws_iam_policy_document" "storefront" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.storefront.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.this.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "storefront" {
  bucket = aws_s3_bucket.storefront.id
  policy = data.aws_iam_policy_document.storefront.json

  depends_on = [aws_s3_bucket_public_access_block.storefront]
}

output "cloudfront_domain" {
  value = aws_cloudfront_distribution.this.domain_name
}

output "distribution_id" {
  value = aws_cloudfront_distribution.this.id
}
