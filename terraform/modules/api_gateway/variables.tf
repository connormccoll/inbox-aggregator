variable "gmail_webhook_lambda_arn" {
  description = "ARN of the gmail-webhook Lambda function."
  type        = string
}

variable "gmail_webhook_lambda_invoke_arn" {
  description = "Invoke ARN of the gmail-webhook Lambda function."
  type        = string
}

variable "subscribe_lambda_arn" {
  description = "ARN of the subscribe Lambda function."
  type        = string
}

variable "subscribe_lambda_invoke_arn" {
  description = "Invoke ARN of the subscribe Lambda function."
  type        = string
}

variable "graphql_lambda_arn" {
  description = "ARN of the graphql-query Lambda function."
  type        = string
}

variable "graphql_lambda_invoke_arn" {
  description = "Invoke ARN of the graphql-query Lambda function."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}
