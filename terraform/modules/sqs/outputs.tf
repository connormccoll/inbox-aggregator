output "queue_url" {
  value = aws_sqs_queue.email_processing.url
}

output "queue_arn" {
  value = aws_sqs_queue.email_processing.arn
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}
