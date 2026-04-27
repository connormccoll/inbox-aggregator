locals {
  prefix = "inbox-aggregator"
}

# ──────────────────────────────────────────────
# Daily Digest — weekdays at market close
# ──────────────────────────────────────────────
resource "aws_cloudwatch_event_rule" "daily_digest" {
  name                = "${local.prefix}-daily-digest"
  description         = "Trigger daily-digest Lambda after market close (weekdays)."
  schedule_expression = var.daily_digest_cron
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "daily_digest" {
  rule      = aws_cloudwatch_event_rule.daily_digest.name
  target_id = "daily-digest-lambda"
  arn       = var.daily_digest_lambda_arn
}

resource "aws_lambda_permission" "daily_digest_invoke" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.daily_digest_lambda_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_digest.arn
}

# ──────────────────────────────────────────────
# Gmail Watch Refresh — once per day
# ──────────────────────────────────────────────
resource "aws_cloudwatch_event_rule" "gmail_watch_refresh" {
  name                = "${local.prefix}-gmail-watch-refresh"
  description         = "Renew Gmail Watch daily (watch expires every 7 days)."
  schedule_expression = "rate(1 day)"
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "gmail_watch_refresh" {
  rule      = aws_cloudwatch_event_rule.gmail_watch_refresh.name
  target_id = "gmail-watch-refresh-lambda"
  arn       = var.gmail_watch_refresh_lambda_arn
}

resource "aws_lambda_permission" "gmail_watch_refresh_invoke" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.gmail_watch_refresh_lambda_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.gmail_watch_refresh.arn
}

# ──────────────────────────────────────────────
# Weekly Digest — every Sunday
# ──────────────────────────────────────────────
resource "aws_cloudwatch_event_rule" "weekly_digest" {
  name                = "${local.prefix}-weekly-digest"
  description         = "Trigger weekly-digest Lambda every Sunday with open position summary."
  schedule_expression = var.weekly_digest_cron
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "weekly_digest" {
  rule      = aws_cloudwatch_event_rule.weekly_digest.name
  target_id = "weekly-digest-lambda"
  arn       = var.weekly_digest_lambda_arn
}

resource "aws_lambda_permission" "weekly_digest_invoke" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.weekly_digest_lambda_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_digest.arn
}
