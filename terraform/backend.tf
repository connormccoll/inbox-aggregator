terraform {
  backend "s3" {
    bucket       = "inbox-aggregator-tf-state"
    key          = "inbox-aggregator/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
    encrypt      = true
  }
}
