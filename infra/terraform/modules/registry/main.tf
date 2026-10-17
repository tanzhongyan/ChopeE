locals {
  repos = {
    catalog_cart = "chopee-catalog-cart"
    checkout     = "chopee-checkout"
  }
}

resource "aws_ecr_repository" "this" {
  for_each = local.repos

  name                 = each.value
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}
