output "recommendations_table_name" {
  value = aws_dynamodb_table.recommendations.name
}

output "recommendations_table_arn" {
  value = aws_dynamodb_table.recommendations.arn
}

output "recommendations_stream_arn" {
  value = aws_dynamodb_table.recommendations.stream_arn
}

output "processed_emails_table_name" {
  value = aws_dynamodb_table.processed_emails.name
}

output "processed_emails_table_arn" {
  value = aws_dynamodb_table.processed_emails.arn
}

output "users_table_name" {
  value = aws_dynamodb_table.users.name
}

output "users_table_arn" {
  value = aws_dynamodb_table.users.arn
}

output "open_positions_table_name" {
  value = aws_dynamodb_table.open_positions.name
}

output "open_positions_table_arn" {
  value = aws_dynamodb_table.open_positions.arn
}

output "feedback_table_name" {
  value = aws_dynamodb_table.feedback.name
}

output "feedback_table_arn" {
  value = aws_dynamodb_table.feedback.arn
}

output "prompts_table_name" {
  value = aws_dynamodb_table.prompts.name
}

output "prompts_table_arn" {
  value = aws_dynamodb_table.prompts.arn
}
