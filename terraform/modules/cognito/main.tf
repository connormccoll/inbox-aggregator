locals {
  prefix = "inbox-aggregator"
}

# ──────────────────────────────────────────────
# User pool
# Email-based accounts. Sign-in is delegated to Google (federated IdP), so the
# pool itself never stores passwords. The invitation password gates activation,
# not authentication (see the redeem-invitation Lambda + the "active" group).
# ──────────────────────────────────────────────
resource "aws_cognito_user_pool" "main" {
  name                     = "${local.prefix}-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
    string_attribute_constraints {
      min_length = 1
      max_length = 256
    }
  }

  tags = {
    Name = "${local.prefix}-users"
  }
}

# Hosted UI domain (Cognito-managed). Prefix must be globally unique within the
# region, so it is suffixed with the AWS account id by the caller.
resource "aws_cognito_user_pool_domain" "main" {
  domain       = var.domain_prefix
  user_pool_id = aws_cognito_user_pool.main.id
}

# ──────────────────────────────────────────────
# Google identity provider
# Created only once Google credentials are supplied. This lets the first
# `terraform apply` stand up the pool + Hosted UI domain (so you can read the
# redirect URI and register the Google web client), then a second apply with
# the credentials set wires up federated sign-in.
# ──────────────────────────────────────────────
resource "aws_cognito_identity_provider" "google" {
  count         = var.google_client_id != "" ? 1 : 0
  user_pool_id  = aws_cognito_user_pool.main.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    client_id        = var.google_client_id
    client_secret    = var.google_client_secret
    authorize_scopes = "openid email profile"
  }

  attribute_mapping = {
    email    = "email"
    username = "sub"
    name     = "name"
  }
}

# ──────────────────────────────────────────────
# "active" group — members have redeemed the invitation password and may call
# the authenticated API. The authorizer checks for this group claim.
# ──────────────────────────────────────────────
resource "aws_cognito_user_group" "active" {
  name         = "active"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Users who have redeemed the invitation password."
}

# ──────────────────────────────────────────────
# App client (SPA — no client secret)
# ──────────────────────────────────────────────
resource "aws_cognito_user_pool_client" "spa" {
  name         = "${local.prefix}-spa"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret = false

  # "Google" once federation is enabled; a placeholder before then so the
  # client is valid on the first apply.
  supported_identity_providers = var.google_client_id != "" ? ["Google"] : ["COGNITO"]

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]

  callback_urls = var.callback_urls
  logout_urls   = var.logout_urls

  # Access/ID tokens valid for 1 hour; refresh for 30 days.
  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  prevent_user_existence_errors = "ENABLED"

  depends_on = [aws_cognito_identity_provider.google]
}
