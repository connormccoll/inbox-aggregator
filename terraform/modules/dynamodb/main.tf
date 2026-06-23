locals {
  prefix = "inbox-aggregator"
}

# ──────────────────────────────────────────────
# Recommendations table
# PK: TICKER#<ticker>  SK: <YYYY-MM-DD>#<message_id>
# GSI: DateIndex — PK: DATE#<date>  SK: TICKER#<ticker>
# ──────────────────────────────────────────────
resource "aws_dynamodb_table" "recommendations" {
  name         = "${local.prefix}-recommendations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "date_pk"
    type = "S"
  }
  attribute {
    name = "ticker_sk"
    type = "S"
  }

  global_secondary_index {
    name            = "DateIndex"
    hash_key        = "date_pk"
    range_key       = "ticker_sk"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  tags = {
    Name = "${local.prefix}-recommendations"
  }
}

# ──────────────────────────────────────────────
# ProcessedEmails table (deduplication)
# PK: <gmail_message_id>
# TTL: 30 days
# ──────────────────────────────────────────────
resource "aws_dynamodb_table" "processed_emails" {
  name         = "${local.prefix}-processed-emails"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"

  attribute {
    name = "PK"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name = "${local.prefix}-processed-emails"
  }
}

# ──────────────────────────────────────────────
# Users table (multi-channel subscribers)
# One partition per user (Cognito sub); one row per profile + per channel.
#   PK: USER#<sub>  SK: PROFILE                    → name, email, status
#   PK: USER#<sub>  SK: CHANNEL#SMS#<phone>        → SMS delivery channel
#   PK: USER#<sub>  SK: CHANNEL#PUSHOVER#<key>     → Pushover delivery channel
# GSI: ActiveChannels — hash: channel_status ("ACTIVE")  range: SK
#   Only verified+opted-in CHANNEL# rows carry channel_status, so PROFILE
#   rows stay out of the index. The dispatcher/digests query this single GSI
#   to fan out a broadcast to every active delivery channel across all users.
# ──────────────────────────────────────────────
resource "aws_dynamodb_table" "users" {
  name         = "${local.prefix}-users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "channel_status"
    type = "S"
  }

  global_secondary_index {
    name            = "ActiveChannels"
    hash_key        = "channel_status"
    range_key       = "SK"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name = "${local.prefix}-users"
  }
}

# ──────────────────────────────────────────────
# OpenPositions table
# Tracks one row per ticker per source.
# BUY/POSITIVE → open_status=OPEN (no TTL)
# SELL/STOP_LOSS → open_status=CLOSED, TTL=7 days (auto-purge after close tra