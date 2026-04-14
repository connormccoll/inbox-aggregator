locals {
  prefix = "inbox-aggregator"
}

# ──────────────────────────────────────────────
# Lambda Layer (shared dependencies)
# ──────────────────────────────────────────────
resource "null_resource" "layer_build" {
  triggers = {
    requirements = filemd5("${path.module}/../lambdas/layer/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<-EOT
      pip install \
        --quiet \
        --target ${path.module}/../.build/layer/python \
        -r ${path.module}/../lambdas/layer/requirements.txt
    EOT
  }
}

data "archive_file" "layer_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../.build/layer"
  output_path = "${path.module}/../.build/layer.zip"
  depends_on  = [null_resource.layer_build]
}

resource "aws_lambda_layer_version" "shared" {
  layer_name          = "${local.prefix}-shared"
  filename            = data.archive_file.layer_zip.output_path
  source_code_hash    = data.archive_file.layer_zip.output_base64sha256
  compatible_runtimes = ["python3.12"]
  description         = "Shared dependencies: google-api-python-client, google-auth, etc."
}

# ──────────────────────────────────────────────
# Modules
# ──────────────────────────────────────────────
module "dynamodb" {
  source      = "./modules/dynamodb"
  environment = var.environment
}

module "sqs" {
  source      = "./modules/sqs"
  environment = var.environment
}

module "secrets" {
  source             = "./modules/secrets"
  gmail_secrets_name = var.gmail_secrets_name
}

# ──────────────────────────────────────────────
# Shared IAM policy documents
# ──────────────────────────────────────────────
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
}

# Policy allowing Lambda to read Gmail OAuth secret
data "aws_iam_policy_document" "read_gmail_secret" {
  statement {
    sid     = "ReadGmailSecret"
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [module.secrets.gmail_secret_arn]
  }
}

# Policy for DynamoDB full access on inbox-aggregator tables
data "aws_iam_policy_document" "dynamodb_readwrite" {
  statement {
    sid    = "DynamoDBReadWrite"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:BatchWriteItem",
    ]
    resources = [
      module.dynamodb.recommendations_table_arn,
      "${module.dynamodb.recommendations_table_arn}/index/*",
      module.dynamodb.holdings_table_arn,
      "${module.dynamodb.holdings_table_arn}/index/*",
      module.dynamodb.subscribers_table_arn,
      "${module.dynamodb.subscribers_table_arn}/index/*",
      module.dynamodb.processed_emails_table_arn,
      module.dynamodb.open_positions_table_arn,
      "${module.dynamodb.open_positions_table_arn}/index/*",
    ]
  }
}

# Policy for SQS send (used by gmail_webhook)
data "aws_iam_policy_document" "sqs_send" {
  statement {
    sid     = "SQSSend"
    effect  = "Allow"
    actions = ["sqs:SendMessage"]
    resources = [module.sqs.queue_arn]
  }
}

# Policy for Bedrock Claude invocation
data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid     = "BedrockInvoke"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:${local.region}::foundation-model/${var.bedrock_model_id}",
    ]
  }
}

# Policy for SNS SMS publish (direct phone number publish — no resource ARN applies)
data "aws_iam_policy_document" "sns_publish" {
  statement {
    sid       = "SNSPublishSMS"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = ["*"]
  }
}

# Policy for SSM Parameter Store (historyId tracking by gmail_webhook)
data "aws_iam_policy_document" "ssm_history_id" {
  statement {
    sid    = "SSMHistoryId"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:PutParameter",
    ]
    resources = [
      "arn:aws:ssm:${local.region}:${local.account_id}:parameter/inbox-aggregator/gmail-history-id",
    ]
  }
}

# ──────────────────────────────────────────────
# Lambda: gmail-webhook
# Triggered by API Gateway; decodes Pub/Sub payload → history.list → SQS
# ──────────────────────────────────────────────
module "lambda_gmail_webhook" {
  source      = "./modules/lambda"
  function_name = "${local.prefix}-gmail-webhook"
  source_dir    = "${path.module}/../lambdas/gmail_webhook"
  timeout       = 30
  layer_arns    = [aws_lambda_layer_version.shared.arn]

  environment_variables = {
    SQS_QUEUE_URL      = module.sqs.queue_url
    GMAIL_SECRET_NAME  = module.secrets.gmail_secret_name
    AWS_REGION_NAME    = var.aws_region
  }

  inline_policies = {
    sqs-send          = data.aws_iam_policy_document.sqs_send.json
    read-gmail-secret = data.aws_iam_policy_document.read_gmail_secret.json
    ssm-history-id    = data.aws_iam_policy_document.ssm_history_id.json
  }
}

# ──────────────────────────────────────────────
# Lambda: email-processor
# SQS trigger; Gmail fetch → dedup → Bedrock → DynamoDB
# ──────────────────────────────────────────────
module "lambda_email_processor" {
  source        = "./modules/lambda"
  function_name = "${local.prefix}-email-processor"
  source_dir    = "${path.module}/../lambdas/email_processor"
  timeout       = 300
  memory_size   = 512
  layer_arns    = [aws_lambda_layer_version.shared.arn]

  environment_variables = {
    RECOMMENDATIONS_TABLE    = module.dynamodb.recommendations_table_name
    HOLDINGS_TABLE           = module.dynamodb.holdings_table_name
    PROCESSED_EMAILS_TABLE   = module.dynamodb.processed_emails_table_name
    OPEN_POSITIONS_TABLE     = module.dynamodb.open_positions_table_name
    GMAIL_SECRET_NAME        = module.secrets.gmail_secret_name
    BEDROCK_MODEL_ID         = var.bedrock_model_id
    AWS_REGION_NAME          = var.aws_region
  }

  inline_policies = {
    dynamodb-readwrite = data.aws_iam_policy_document.dynamodb_readwrite.json
    bedrock-invoke     = data.aws_iam_policy_document.bedrock_invoke.json
    read-gmail-secret  = data.aws_iam_policy_document.read_gmail_secret.json
  }
}

# SQS → email-processor event source mapping
resource "aws_lambda_event_source_mapping" "sqs_to_email_processor" {
  event_source_arn                   = module.sqs.queue_arn
  function_name                      = module.lambda_email_processor.function_arn
  batch_size                         = 1
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]
}

# SQS receive permission for email-processor
resource "aws_iam_role_policy" "email_processor_sqs_receive" {
  name = "sqs-receive"
  role = module.lambda_email_processor.role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = module.sqs.queue_arn
    }]
  })
}

# ──────────────────────────────────────────────
# Lambda: sns-dispatcher
# DynamoDB Streams consumer; checks Holdings → sends SMS
# ──────────────────────────────────────────────
module "lambda_sns_dispatcher" {
  source        = "./modules/lambda"
  function_name = "${local.prefix}-sns-dispatcher"
  source_dir    = "${path.module}/../lambdas/sns_dispatcher"
  timeout       = 60
  layer_arns    = [aws_lambda_layer_version.shared.arn]

  environment_variables = {
    HOLDINGS_TABLE        = module.dynamodb.holdings_table_name
    SUBSCRIBERS_TABLE     = module.dynamodb.subscribers_table_name
    OPEN_POSITIONS_TABLE  = module.dynamodb.open_positions_table_name
    AWS_REGION_NAME       = var.aws_region
  }

  inline_policies = {
    dynamodb-readwrite = data.aws_iam_policy_document.dynamodb_readwrite.json
    sns-publish        = data.aws_iam_policy_document.sns_publish.json
  }
}

# DynamoDB Streams → sns-dispatcher event source mapping
resource "aws_lambda_event_source_mapping" "recommendations_stream_to_dispatcher" {
  event_source_arn              = module.dynamodb.recommendations_stream_arn
  function_name                 = module.lambda_sns_dispatcher.function_arn
  starting_position             = "LATEST"
  batch_size                    = 10
  bisect_batch_on_function_error = true

  filter_criteria {
    filter {
      # Only process INSERT events
      pattern = jsonencode({ eventName = ["INSERT"] })
    }
  }
}

# DynamoDB Streams receive permission for sns-dispatcher
resource "aws_iam_role_policy" "sns_dispatcher_streams" {
  name = "dynamodb-streams"
  role = module.lambda_sns_dispatcher.role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:DescribeStream", "dynamodb:ListStreams"]
      Resource = module.dynamodb.recommendations_stream_arn
    }]
  })
}

# ──────────────────────────────────────────────
# Lambda: daily-digest
# EventBridge cron; queries today's recommendations → sends digest SMS
# ──────────────────────────────────────────────
module "lambda_daily_digest" {
  source        = "./modules/lambda"
  function_name = "${local.prefix}-daily-digest"
  source_dir    = "${path.module}/../lambdas/daily_digest"
  timeout       = 60
  layer_arns    = [aws_lambda_layer_version.shared.arn]

  environment_variables = {
    RECOMMENDATIONS_TABLE = module.dynamodb.recommendations_table_name
    SUBSCRIBERS_TABLE     = module.dynamodb.subscribers_table_name
    AWS_REGION_NAME       = var.aws_region
  }

  inline_policies = {
    dynamodb-readwrite = data.aws_iam_policy_document.dynamodb_readwrite.json
    sns-publish        = data.aws_iam_policy_document.sns_publish.json
  }
}

# ──────────────────────────────────────────────
# Lambda: weekly-digest
# EventBridge cron; scans OpenPositions → sends weekly SMS summary
# ──────────────────────────────────────────────
module "lambda_weekly_digest" {
  source        = "./modules/lambda"
  function_name = "${local.prefix}-weekly-digest"
  source_dir    = "${path.module}/../lambdas/weekly_digest"
  timeout       = 60
  layer_arns    = [aws_lambda_layer_version.shared.arn]

  environment_variables = {
    OPEN_POSITIONS_TABLE  = module.dynamodb.open_positions_table_name
    HOLDINGS_TABLE        = module.dynamodb.holdings_table_name
    SUBSCRIBERS_TABLE     = module.dynamodb.subscribers_table_name
    AWS_REGION_NAME       = var.aws_region
  }

  inline_policies = {
    dynamodb-readwrite = data.aws_iam_policy_document.dynamodb_readwrite.json
    sns-publish        = data.aws_iam_policy_document.sns_publish.json
  }
}

# ──────────────────────────────────────────────
# Lambda: gmail-watch-refresh
# EventBridge rate(1 day); renews Gmail Watch
# ──────────────────────────────────────────────
module "lambda_gmail_watch_refresh" {
  source        = "./modules/lambda"
  function_name = "${local.prefix}-gmail-watch-refresh"
  source_dir    = "${path.module}/../lambdas/gmail_watch_refresh"
  timeout       = 30
  layer_arns    = [aws_lambda_layer_version.shared.arn]

  environment_variables = {
    GMAIL_SECRET_NAME = module.secrets.gmail_secret_name
    GCP_TOPIC_NAME    = "projects/${var.gcp_project_id}/topics/inbox-aggregator-gmail-notifications"
    AWS_REGION_NAME   = var.aws_region
  }

  inline_policies = {
    read-gmail-secret = data.aws_iam_policy_document.read_gmail_secret.json
  }
}

# ──────────────────────────────────────────────
# API Gateway (depends on gmail-webhook Lambda)
# ──────────────────────────────────────────────
module "api_gateway" {
  source                          = "./modules/api_gateway"
  gmail_webhook_lambda_arn        = module.lambda_gmail_webhook.function_arn
  gmail_webhook_lambda_invoke_arn = module.lambda_gmail_webhook.invoke_arn
  environment                     = var.environment
}

# ──────────────────────────────────────────────
# EventBridge schedules
# ──────────────────────────────────────────────
module "eventbridge" {
  source                         = "./modules/eventbridge"
  daily_digest_cron              = var.daily_digest_cron
  daily_digest_lambda_arn        = module.lambda_daily_digest.function_arn
  gmail_watch_refresh_lambda_arn = module.lambda_gmail_watch_refresh.function_arn
  weekly_digest_cron             = var.weekly_digest_cron
  weekly_digest_lambda_arn       = module.lambda_weekly_digest.function_arn
}

# ──────────────────────────────────────────────
# CloudWatch alarm: DLQ depth
# Fires when messages accumulate in the dead-letter queue (processing failures)
# ──────────────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${local.prefix}-dlq-not-empty"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Messages are accumulating in the email-processing DLQ. Check Lambda logs for errors."
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = module.sqs.dlq_name
  }

  # alarm_actions = []  # Wire an SNS topic here to receive email/SMS alerts on DLQ depth
}

# ──────────────────────────────────────────────
# GCP Pub/Sub
# ──────────────────────────────────────────────
module "pubsub" {
  source         = "./modules/pubsub"
  gcp_project_id = var.gcp_project_id
  push_endpoint  = "${module.api_gateway.base_url}/gmail-push"
}
