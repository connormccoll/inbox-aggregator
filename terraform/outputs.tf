output "api_gateway_url" {
  description = "Base URL of the API Gateway (used by GCP Pub/Sub push subscription)."
  value       = module.api_gateway.base_url
}

output "gmail_push_endpoint" {
  description = "Full URL for the Gmail Pub/Sub push endpoint."
  value       = "${module.api_gateway.base_url}/gmail-push"
}

output "graphql_endpoint" {
  description = "GraphQL-style endpoint for chat and table queries (Cognito-authorized)."
  value       = "${module.api_gateway.base_url}/graphql"
}

output "redeem_endpoint" {
  description = "Invitation-redemption endpoint (Cognito-authorized)."
  value       = "${module.api_gateway.base_url}/redeem"
}

output "channels_endpoint" {
  description = "Delivery-channel management endpoint (Cognito-authorized)."
  value       = "${module.api_gateway.base_url}/channels"
}

output "cognito_user_pool_id" {
  description = "Cognito user pool ID."
  value       = module.cognito.user_pool_id
}

output "cognito_client_id" {
  description = "Cognito SPA app client ID (used by the frontend)."
  value       = module.cognito.user_pool_client_id
}

output "cognito_hosted_ui_domain" {
  description = "Cognito Hosted UI base URL for Google sign-in."
  value       = module.cognito.hosted_ui_domain
}

output "cognito_redirect_uri" {
  description = "Authorized redirect URI to register in the Google OAuth client."
  value       = "${module.cognito.hosted_ui_domain}/oauth2/idpresponse"
}

output "email_processing_queue_url" {
  description = "SQS queue URL for email processing."
  value       = module.sqs.queue_url
}

output "recommendations_table_name" {
  description = "DynamoDB Recommendations table name."
  value       = module.dynamodb.recommendations_table_name
}

output "users_table_name" {
  description = "DynamoDB Users table name."
  value       = module.dynamodb.users_table_name
}

output "frontend_url" {
  description = "CloudFront HTTPS URL for the subscription portal."
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "frontend_bucket_name" {
  description = "S3 bucket name for the frontend static assets."
  value       = aws_s3_bucket.frontend.id
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID (used for cache invalidations)."
  value       = aws_cloudfront_distribution.frontend.id
}
