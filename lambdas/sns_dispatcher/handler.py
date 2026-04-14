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
OPEN_POSITIONS_TABLE = os.environ["OPEN_POSITIONS_TABLE"]

CLOSE_ACTIONS = {"SELL", "STOP_LOSS", "NEGATIVE"}


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


def _get_open_position(ticker: str, source: str) -> dict | None:
    """Fetch OpenPositions row for a specific ticker+source to get original rec date."""
    table = dynamodb.Table(OPEN_POSITIONS_TABLE)
    resp = table.get_item(
        Key={"PK": f"TICKER#{ticker}", "SK": f"SOURCE#{source}"},
    )
    return resp.get("Item")


def _format_sms(rec: dict, holdings: list[dict], open_position: dict | None = None) -> str:
    """Format a concise SMS alert under 320 chars."""
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

    # For close actions, include when this source originally recommended the position
    if action in CLOSE_ACTIONS and open_position:
        first_rec = open_position.get("first_rec_date")
        if first_rec:
            lines.append(f"Orig rec: {first_rec}")

    message = "\n".join(lines)
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

        # For close actions on owned positions, fetch original rec date from OpenPositions
        open_position = None
        if rec.get("action", "").upper() in CLOSE_ACTIONS:
            open_position = _get_open_position(ticker, rec.get("source", ""))

        message = _format_sms(rec, holdings, open_position)
        logger.info("Sending immediate alert for ticker=%s to %d subscribers", ticker, len(subscribers))

        for subscriber in subscribers:
            phone = subscriber["PK"].removeprefix("SUBSCRIBER#")
            try:
                _send_sms(phone, message)
                logger.info("SMS sent to %s for ticker=%s", phone, ticker)
            except Exception as exc:
                # Log and continue — don't fail the entire batch for one subscriber
                logger.error("Failed to send SMS to %s: %s", phone, exc)
