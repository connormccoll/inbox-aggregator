variable "gmail_webhook_lambda_arn" {
  description = "ARN of the gmail-webhook Lambda function."
  type        = string
}

variable "gmail_webhook_lambda_invoke_arn" {
  description = "Invoke ARN of the gmail-webhook Lambda function."
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

variable "redeem_lambda_arn" {
  description = "ARN of the redeem-invitation Lambda function."
  type        = string
}

variable "redeem_lambda_invoke_arn" {
  description = "Invoke ARN of the redeem-invitation Lambda function."
  type        = string
}

variable "channels_lambda_arn" {
  description = "ARN of the channels Lambda function."
  type        = string
}

variable "channels_lambda_invoke_arn" {
  description = "Invoke ARN of the channels Lambda function."
  type        = string
}

variable "cognito_user_pool_arn" {
  description = "ARN of the Cognito user pool backing the API authorizer."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}
