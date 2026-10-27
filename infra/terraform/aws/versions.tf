terraform {
  required_version = ">= 1.6.0"

  # Partial configuration. Bucket, key, region, and KMS come from backend.hcl.
  # use_lockfile is the Terraform 1.11 S3 lock. init -backend=false still works.
  backend "s3" {
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}

locals {
  tags = {
    Project    = "ai-gateway"
    Boundary   = var.boundary
    ManagedBy  = "terraform"
    Repository = "multicloud-ai-gateway"
  }
}
