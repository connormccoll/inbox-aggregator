locals {
  prefix = "inbox-aggregator"
}

resource "aws_sqs_queue" "dlq" {
  name                       = "${local.prefix}-email-processing-dlq"
  message_retention_seconds  = 1209600 # 14 days
  receive_wait_time_seconds  = 20

  tags = {
    Name = "${local.prefix}-email-processing-dlq"
  }
}

resource "aws_sqs_queue" "email_processing" {
  name                       = "${local.prefix}-email-processing"
  visibility_timeout_seconds = 300 # 5 minutes — matches Lambda max timeout for processor
  message_retention_seconds  = 86400 # 1 day
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Name = "${local.prefix}-email-processing"
  }
}
