output "api_gateway_url" {
  description = "Base URL of the API Gateway (used by GCP Pub/Sub push subscription)."
  value       = module.api_gateway.base_url
}

output "gmail_push_endpoint" {
  description = "Full URL for the Gmail Pub/Sub push endpoint."
  value       = "${module.api_gateway.base_url}/gmail-push"
}

output "email_processing_queue_url" {
  description = "SQS queue URL for email processing."
  value       = module.sqs.queue_url
}

output "recommendations_table_name" {
  description = "DynamoDB Recommendations table name."
  value       = module.dynamodb.recommendations_table_name
}

output "subscribers_table_name" {
  description = "DynamoDB Subscribers table name."
  value       = module.dynamodb.subscribers_table_name
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
