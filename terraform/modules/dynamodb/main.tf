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
# Holdings table
# PK: PORTFOLIO#<name>  SK: TICKER#<ticker>
# GSI: TickerIndex — PK: TICKER#<ticker>  SK: PORTFOLIO#<name>
# ──────────────────────────────────────────────
resource "aws_dynamodb_table" "holdings" {
  name         = "${local.prefix}-holdings"
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
    name = "ticker_pk"
    type = "S"
  }
  attribute {
    name = "portfolio_sk"
    type = "S"
  }

  global_secondary_index {
    name            = "TickerIndex"
    hash_key        = "ticker_pk"
    range_key       = "portfolio_sk"
    projection_type = "ALL"
  }

  tags = {
    Name = "${local.prefix}-holdings"
  }
}

# ──────────────────────────────────────────────
# Subscribers table
# PK: SUBSCRIBER#<phone>
# GSI: StatusIndex — PK: status  SK: PK (phone)
# ──────────────────────────────────────────────
resource "aws_dynamodb_table" "subscribers" {
  name         = "${local.prefix}-subscribers"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "status"
    type = "S"
  }

  global_secondary_index {
    name            = "StatusIndex"
    hash_key        = "status"
    range_key       = "PK"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name = "${local.prefix}-subscribers"
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
# OpenPositions table
# Tracks one row per ticker per source.
# BUY/POSITIVE → open_status=OPEN (no TTL)
# SELL/STOP_LOSS → open_status=CLOSED, TTL=7 days (auto-purge after close tracking window)
# PK: TICKER#<ticker>  SK: SOURCE#<source_name>
# ──────────────────────────────────────────────
resource "aws_dynamodb_table" "open_positions" {
  name         = "${local.prefix}-open-positions"
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

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name = "${local.prefix}-open-positions"
  }
}
