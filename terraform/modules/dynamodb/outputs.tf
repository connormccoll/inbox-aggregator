output "recommendations_table_name" {
  value = aws_dynamodb_table.recommendations.name
}

output "recommendations_table_arn" {
  value = aws_dynamodb_table.recommendations.arn
}

output "recommendations_stream_arn" {
  value = aws_dynamodb_table.recommendations.stream_arn
}

output "holdings_table_name" {
  value = aws_dynamodb_table.holdings.name
}

output "holdings_table_arn" {
  value = aws_dynamodb_table.holdings.arn
}

output "subscribers_table_name" {
  value = aws_dynamodb_table.subscribers.name
}

output "subscribers_table_arn" {
  value = aws_dynamodb_table.subscribers.arn
}

output "processed_emails_table_name" {
  value = aws_dynamodb_table.processed_emails.name
}

output "processed_emails_table_arn" {
  value = aws_dynamodb_table.processed_emails.arn
}

output "open_positions_table_name" {
  value = aws_dynamodb_table.open_positions.name
}

output "open_positions_table_arn" {
  value = aws_dynamodb_table.open_positions.arn
}
