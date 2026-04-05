terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.90"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "inbox-aggregator"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = "us-central1"
}
