"""
sns_dispatcher/handler.py

DynamoDB Streams consumer. Fires on INSERT events from the Recommendations table.
For each new recommendation, checks if the ticker is in any tracked portfolio.
If it is, sends an immediate SMS alert to all active subscribers.
"""

import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)
sns = boto3.client("sns", region_name=region)

HOLDINGS_TABLE = os.environ["HOLDINGS_TABLE"]
SUBSCRIBERS_TABLE = os.environ["SUBSCRIBERS_TABLE"]


def _get_active_subscribers() -> list[dict]:
    table = dynamodb.Table(SUBSCRIBERS_TABLE)
    resp = table.query(
        IndexName="StatusIndex",
        KeyConditionExpression=Key("status").eq("ACTIVE"),
    )
    return resp.get("Items", [])


def _get_holdings_for_ticker(ticker: str) -> list[dict]:
    """Query TickerIndex GSI to find all portfolios that hold this ticker."""
    table = dynamodb.Table(HOLDINGS_TABLE)
    resp = table.query(
        IndexName="TickerIndex",
        KeyConditionExpression=Key("ticker_pk").eq(f"TICKER#{ticker}"),
    )
    return resp.get("Items", [])


def _format_sms(rec: dict, holdings: list[dict]) -> str:
    """Format a concise SMS alert under 160 chars."""
    ticker = rec.get("ticker", "")
    action = rec.get("action", "")
    source = rec.get("source", "")
    email_date = rec.get("email_date", "")
    stop_loss = rec.get("stop_loss_price")
    price_target = rec.get("price_target")

    # Portfolio context
    portfolio_lines = []
    for h in holdings:
        name = h.get("portfolio_name", "")
        shares = h.get("shares")
        if shares:
            portfolio_lines.append(f"{name} ({shares} shares)")
        else:
            portfolio_lines.append(name)
    portfolio_str = ", ".join(portfolio_lines)

    lines = [f"[INBOX] {action}: {ticker} | {source}"]
    if stop_loss:
        lines.append(f"Stop: ${stop_loss}")
    if price_target:
        lines.append(f"Target: ${price_target}")
    lines.append(f"Portfolio: {portfolio_str}")
    lines.append(email_date)

    message = "\n".join(lines)

    # Truncate to 320 chars (2 SMS segments max) to avoid excessive billing
    return message[:320]


def _send_sms(phone_number: str, message: str) -> None:
    sns.publish(
        PhoneNumber=phone_number,
        Message=message,
        MessageAttributes={
            "AWS.SNS.SMS.SMSType": {
                "DataType": "String",
                "StringValue": "Transactional",
            }
        },
    )


def _unmarshal_rec(new_image: dict) -> dict:
    """Convert DynamoDB stream NewImage format to plain dict."""
    deserializer = boto3.dynamodb.types.TypeDeserializer()
    return {k: deserializer.deserialize(v) for k, v in new_image.items()}


def lambda_handler(event: dict, context) -> None:
    subscribers = _get_active_subscribers()
    if not subscribers:
        logger.info("No active subscribers — skipping dispatch.")
        return

    for record in event.get("Records", []):
        if record.get("eventName") != "INSERT":
            continue

        new_image = record.get("dynamodb", {}).get("NewImage")
        if not new_image:
            continue

        rec = _unmarshal_rec(new_image)
        ticker = rec.get("ticker", "").upper()
        if not ticker:
            continue

        holdings = _get_holdings_for_ticker(ticker)
        if not holdings:
            logger.info("ticker=%s not in any portfolio — no immediate alert.", ticker)
            continue

        message = _format_sms(rec, holdings)
        logger.info("Sending immediate alert for ticker=%s to %d subscribers", ticker, len(subscribers))

        for subscriber in subscribers:
            phone = subscriber["PK"].removeprefix("SUBSCRIBER#")
            try:
                _send_sms(phone, message)
                logger.info("SMS sent to %s for ticker=%s", phone, ticker)
            except Exception as exc:
                # Log and continue — don't fail the entire batch for one subscriber
                logger.error("Failed to send SMS to %s: %s", phone, exc)
