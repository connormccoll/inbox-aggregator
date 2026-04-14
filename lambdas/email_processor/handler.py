"""
email_processor/handler.py

SQS-triggered Lambda. For each message ID:
  1. Fetch full email content via Gmail API
  2. Atomically mark as processed in DynamoDB (dedup)
  3. Invoke Bedrock Claude to extract stock recommendations + portfolio data
  4. Write Recommendations to DynamoDB
  5. Upsert Holdings to DynamoDB (if portfolio update found)
"""

import base64
import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from gmail_client import build_gmail_service

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)
bedrock = boto3.client("bedrock-runtime", region_name=region)

RECOMMENDATIONS_TABLE = os.environ["RECOMMENDATIONS_TABLE"]
HOLDINGS_TABLE = os.environ["HOLDINGS_TABLE"]
PROCESSED_EMAILS_TABLE = os.environ["PROCESSED_EMAILS_TABLE"]
OPEN_POSITIONS_TABLE = os.environ["OPEN_POSITIONS_TABLE"]
BEDROCK_MODEL_ID = os.environ["BEDROCK_MODEL_ID"]

PROCESSED_TABLE_TTL_DAYS = 30
RECOMMENDATIONS_TTL_DAYS = 365
CLOSE_TRACKING_DAYS = 7  # Days to keep CLOSED open-position rows before TTL purge

# Actions that open/maintain a position
OPEN_ACTIONS = {"BUY", "POSITIVE"}
# Actions that close a position
CLOSE_ACTIONS = {"SELL", "STOP_LOSS", "NEGATIVE"}

EXTRACTION_PROMPT = """You are a financial email analyst. Analyse the following email and extract all stock trading information.

Return ONLY a valid JSON object with this exact structure (no markdown, no explanation):
{
  "recommendations": [
    {
      "ticker": "AAPL",
      "action": "BUY",
      "sentiment": "brief quote or rationale from the email",
      "confidence": "HIGH",
      "price_target": null,
      "stop_loss_price": null
    }
  ],
  "portfolio_update": {
    "portfolio_name": "Growth Portfolio",
    "holdings": [
      {"ticker": "AAPL", "shares": 100}
    ]
  },
  "source_name": "TradeSmith",
  "email_type": "STOP_LOSS_ALERT"
}

Rules:
- action must be one of: BUY, SELL, STOP_LOSS, HOLD, POSITIVE, NEGATIVE
  - STOP_LOSS: TradeSmith or any stop-loss alert
  - BUY: explicit buy recommendation
  - SELL: explicit sell recommendation
  - HOLD: hold recommendation
  - POSITIVE: positive/bullish mention without explicit buy
  - NEGATIVE: negative/bearish mention without explicit sell
- confidence: HIGH (explicit rec), MEDIUM (implied), LOW (brief mention)
- price_target: numeric if stated, else null
- stop_loss_price: numeric if stated, else null
- portfolio_update: only if the email contains a portfolio listing with holdings; null otherwise
- source_name: the newsletter or service name
- email_type: NEWSLETTER, STOP_LOSS_ALERT, PORTFOLIO_UPDATE, or OTHER
- If no stock recommendations are found, return an empty recommendations array
- ticker must be the stock exchange symbol (e.g. AAPL, not Apple)

Email subject: {subject}
Email from: {sender}
Email date: {email_date}

Email body:
{body}"""


def _get_email_content(message_id: str) -> dict:
    service = build_gmail_service()
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()

    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    subject = headers.get("subject", "")
    sender = headers.get("from", "")
    date_str = headers.get("date", "")

    body_text = _extract_body(msg["payload"])

    return {
        "message_id": message_id,
        "subject": subject,
        "sender": sender,
        "date": date_str,
        "body": body_text,
    }


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from a MIME payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    # Prefer text/plain over text/html
    parts = payload.get("parts", [])
    plain_parts = [p for p in parts if p.get("mimeType") == "text/plain"]
    html_parts = [p for p in parts if p.get("mimeType") == "text/html"]
    other_parts = [p for p in parts if p.get("mimeType", "").startswith("multipart/")]

    for part in plain_parts + other_parts + html_parts:
        result = _extract_body(part)
        if result:
            return result

    return ""


def _mark_processed(table, message_id: str) -> bool:
    """
    Atomically insert message_id. Returns True if newly inserted,
    False if already exists (duplicate). Uses ConditionExpression to prevent races.
    """
    ttl = int(time.time()) + (PROCESSED_TABLE_TTL_DAYS * 86400)
    try:
        table.put_item(
            Item={
                "PK": message_id,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "ttl": ttl,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def _extract_with_bedrock(email: dict) -> dict:
    prompt = EXTRACTION_PROMPT.format(
        subject=email["subject"],
        sender=email["sender"],
        email_date=email["date"],
        body=email["body"][:8000],  # ~8k chars to stay within token budget
    )

    response = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )

    raw = json.loads(response["body"].read())
    text = raw["content"][0]["text"].strip()

    # Strip any accidental markdown fencing
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    return json.loads(text)


def _update_open_positions(
    open_positions_table,
    ticker: str,
    source: str,
    action: str,
    confidence: str,
    email_date: str,
) -> None:
    """
    Maintain the OpenPositions table:
    - BUY/POSITIVE → upsert as OPEN (increment rec_count, keep first_rec_date unchanged).
    - SELL/STOP_LOSS/NEGATIVE → upsert as CLOSED with 7-day TTL.
    """
    pk = f"TICKER#{ticker}"
    sk = f"SOURCE#{source}"
    now_iso = datetime.now(timezone.utc).isoformat()

    if action in OPEN_ACTIONS:
        # SET fields that always update; ADD rec_count; SET first_rec_date only if not yet present
        open_positions_table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression=(
                "SET #action = :action, confidence = :confidence, "
                "latest_rec_date = :date, ticker = :ticker, #source = :source, "
                "open_status = :status, updated_at = :now "
                "ADD rec_count :one "
                "REMOVE close_action, close_date, #ttl"
            ),
            ExpressionAttributeNames={
                "#action": "action",
                "#source": "source",
                "#ttl": "ttl",
            },
            ExpressionAttributeValues={
                ":action": action,
                ":confidence": confidence,
                ":date": email_date,
                ":ticker": ticker,
                ":source": source,
                ":status": "OPEN",
                ":now": now_iso,
                ":one": 1,
            },
        )
        # Set first_rec_date only if this is the first mention
        try:
            open_positions_table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET first_rec_date = :date",
                ConditionExpression="attribute_not_exists(first_rec_date)",
                ExpressionAttributeValues={":date": email_date},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    elif action in CLOSE_ACTIONS:
        close_ttl = int(time.time()) + (CLOSE_TRACKING_DAYS * 86400)
        open_positions_table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression=(
                "SET #action = :action, confidence = :confidence, "
                "latest_rec_date = :date, ticker = :ticker, #source = :source, "
                "open_status = :status, close_action = :action, close_date = :date, "
                "#ttl = :ttl, updated_at = :now "
                "ADD rec_count :one"
            ),
            ExpressionAttributeNames={
                "#action": "action",
                "#source": "source",
                "#ttl": "ttl",
            },
            ExpressionAttributeValues={
                ":action": action,
                ":confidence": confidence,
                ":date": email_date,
                ":ticker": ticker,
                ":source": source,
                ":status": "CLOSED",
                ":ttl": close_ttl,
                ":now": now_iso,
                ":one": 1,
            },
        )
        # Set first_rec_date only if this is the first mention
        try:
            open_positions_table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET first_rec_date = :date",
                ConditionExpression="attribute_not_exists(first_rec_date)",
                ExpressionAttributeValues={":date": email_date},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    logger.info("Updated open position: ticker=%s source=%s action=%s status=%s",
                ticker, source, action, "OPEN" if action in OPEN_ACTIONS else "CLOSED")


def _write_recommendations(recommendations_table, holdings_table, open_positions_table, email: dict, extracted: dict) -> None:
    email_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    message_id = email["message_id"]
    source_name = extracted.get("source_name", "Unknown")
    ttl = int(time.time()) + (RECOMMENDATIONS_TTL_DAYS * 86400)

    for rec in extracted.get("recommendations", []):
        ticker = rec.get("ticker", "").upper().strip()
        if not ticker:
            continue

        action = rec.get("action", "UNKNOWN").upper()
        sentiment = rec.get("sentiment", "")
        confidence = rec.get("confidence", "MEDIUM")
        price_target = rec.get("price_target")
        stop_loss_price = rec.get("stop_loss_price")

        # Update OpenPositions BEFORE writing to Recommendations so the
        # DynamoDB Streams dispatcher can immediately see the current open state.
        _update_open_positions(open_positions_table, ticker, source_name, action, confidence, email_date)

        item = {
            "PK": f"TICKER#{ticker}",
            "SK": f"{email_date}#{message_id}",
            # GSI keys
            "date_pk": f"DATE#{email_date}",
            "ticker_sk": f"TICKER#{ticker}",
            # Data
            "ticker": ticker,
            "action": action,
            "sentiment": sentiment,
            "confidence": confidence,
            "source": source_name,
            "email_date": email_date,
            "email_subject": email["subject"],
            "email_sender": email["sender"],
            "email_type": extracted.get("email_type", "NEWSLETTER"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ttl": ttl,
        }

        if price_target is not None:
            item["price_target"] = str(price_target)
        if stop_loss_price is not None:
            item["stop_loss_price"] = str(stop_loss_price)

        recommendations_table.put_item(Item=item)
        logger.info("Wrote recommendation: ticker=%s action=%s source=%s", ticker, action, source_name)

    # Update portfolio holdings if present
    portfolio_update = extracted.get("portfolio_update")
    if portfolio_update and isinstance(portfolio_update, dict):
        portfolio_name = portfolio_update.get("portfolio_name", "Default")
        holdings = portfolio_update.get("holdings", [])
        updated_at = datetime.now(timezone.utc).isoformat()

        for holding in holdings:
            ticker = holding.get("ticker", "").upper().strip()
            shares = holding.get("shares")
            if not ticker:
                continue

            holdings_table.put_item(
                Item={
                    "PK": f"PORTFOLIO#{portfolio_name}",
                    "SK": f"TICKER#{ticker}",
                    # GSI keys
                    "ticker_pk": f"TICKER#{ticker}",
                    "portfolio_sk": f"PORTFOLIO#{portfolio_name}",
                    # Data
                    "ticker": ticker,
                    "portfolio_name": portfolio_name,
                    "shares": str(shares) if shares is not None else None,
                    "last_updated": updated_at,
                }
            )
            logger.info("Upserted holding: portfolio=%s ticker=%s shares=%s", portfolio_name, ticker, shares)


def lambda_handler(event: dict, context) -> dict:
    """
    SQS batch handler. Returns partial failures using ReportBatchItemFailures.
    """
    processed_emails_table = dynamodb.Table(PROCESSED_EMAILS_TABLE)
    recommendations_table = dynamodb.Table(RECOMMENDATIONS_TABLE)
    holdings_table = dynamodb.Table(HOLDINGS_TABLE)
    open_positions_table = dynamodb.Table(OPEN_POSITIONS_TABLE)

    failed_items = []

    for record in event.get("Records", []):
        receipt_handle = record["receiptHandle"]
        item_id = record["messageId"]

        try:
            body = json.loads(record["body"])
            message_id = body["message_id"]

            # Step 1: Atomic dedup
            if not _mark_processed(processed_emails_table, message_id):
                logger.info("Duplicate message_id=%s — skipping.", message_id)
                continue

            # Step 2: Fetch email
            email = _get_email_content(message_id)
            logger.info("Fetched email: subject=%r sender=%r", email["subject"], email["sender"])

            # Step 3: Extract with Bedrock
            extracted = _extract_with_bedrock(email)
            logger.info(
                "Extraction result: %d recommendations, portfolio_update=%s",
                len(extracted.get("recommendations", [])),
                bool(extracted.get("portfolio_update")),
            )

            # Step 4: Write to DynamoDB
            _write_recommendations(recommendations_table, holdings_table, open_positions_table, email, extracted)

        except Exception as exc:
            logger.exception("Failed to process SQS record messageId=%s: %s", item_id, exc)
            failed_items.append({"itemIdentifier": item_id})

    return {"batchItemFailures": failed_items}
