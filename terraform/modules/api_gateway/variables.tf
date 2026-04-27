variable "gmail_webhook_lambda_arn" {
  description = "ARN of the gmail-webhook Lambda function."
  type        = string
}

variable "gmail_webhook_lambda_invoke_arn" {
  description = "Invoke ARN of the gmail-webhook Lambda function."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}
