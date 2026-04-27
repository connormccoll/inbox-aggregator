variable "daily_digest_cron" {
  description = "EventBridge cron expression for the daily digest Lambda."
  type        = string
}

variable "daily_digest_lambda_arn" {
  description = "ARN of the daily-digest Lambda function."
  type        = string
}

variable "gmail_watch_refresh_lambda_arn" {
  description = "ARN of the gmail-watch-refresh Lambda function."
  type        = string
}

variable "weekly_digest_cron" {
  description = "EventBridge cron expression for the weekly digest Lambda."
  type        = string
}

variable "weekly_digest_lambda_arn" {
  description = "ARN of the weekly-digest Lambda function."
  type        = string
}
