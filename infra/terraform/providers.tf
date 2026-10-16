provider "aws" {
  region = "ap-southeast-1"

  default_tags {
    tags = {
      Project = "chopee"
      Run     = var.run_id
      Owner   = var.owner
    }
  }
}
