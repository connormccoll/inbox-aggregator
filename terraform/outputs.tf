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

output "holdings_table_name" {
  description = "DynamoDB Holdings table name."
  value       = module.dynamodb.holdings_table_name
}

output "subscribers_table_name" {
  description = "DynamoDB Subscribers table name."
  value       = module.dynamodb.subscribers_table_name
}
