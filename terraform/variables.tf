variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (e.g. prod, dev)."
  type        = string
  default     = "prod"
}

variable "gcp_project_id" {
  description = "Google Cloud project ID for Pub/Sub resources."
  type        = string
}

variable "bedrock_model_id" {
  description = "AWS Bedrock model ID for email extraction."
  type        = string
  default     = "anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "daily_digest_cron" {
  description = "EventBridge cron for the daily digest Lambda (UTC). Default: weekdays 9:30 PM UTC (≈ 4:30 PM EST / 5:30 PM EDT)."
  type        = string
  default     = "cron(30 21 ? * MON-FRI *)"
}

variable "gmail_secrets_name" {
  description = "AWS Secrets Manager secret name for Gmail OAuth credentials."
  type        = string
  default     = "inbox-aggregator/gmail"
}

variable "weekly_digest_cron" {
  description = "EventBridge cron for weekly digest Lambda (UTC). Default: Sundays 7 PM UTC (3 PM ET)."
  type        = string
  default     = "cron(0 19 ? * SUN *)"
}

variable "origination_number" {
  description = "Toll-free origination phone number for SMS sends (E.164 format)."
  type        = string
  default     = "+18882648390"
}
