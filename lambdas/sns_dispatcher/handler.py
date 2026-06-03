"""
sns_dispatcher/handler.py

DynamoDB Streams consumer. Fires on INSERT events from the Recommendations table.
Sends immediate alerts to active subscribers based on action and urgency rules.
"""

import logging
import os
import urllib.parse
import urllib.request

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)
sns = boto3.client("sns", region_name=region)

SUBSCRIBERS_TABLE = os.environ["SUBSCRIBERS_TABLE"]
OPEN_POSITIONS_TABLE = os.environ["OPEN_POSITIONS_TABLE"]
ORIGINATION_NUMBER = os.environ.get("ORIGINATION_NUMBER", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")

CLOSE_ACTIONS = {"SELL", "STOP_LOSS", "NEGATIVE", "CLOSE"}


def _get_active_subscribers() -> list[dict]:
    table = dynamodb.Table(SUBSCRIBERS_TABLE)
    resp = table.query(
        IndexName="StatusIndex",
        KeyConditionExpression=Key("status").eq("ACTIVE"),
    )
    return resp.get("Items", [])


def _get_open_position(ticker: str, source: str) -> dict | None:
    """Fetch OpenPositions row for a specific ticker+source to get original rec date."""
    table = dynamodb.Table(OPEN_POSITIONS_TABLE)
    resp = table.get_item(
        Key={"PK": f"TICKER#{ticker}", "SK": f"SOURCE#{source}"},
    )
    return resp.get("Item")


def _format_sms(rec: dict, open_position: dict | None = None) -> str:
    """Format a concise alert message."""
    ticker = rec.get("ticker", "")
    action = rec.get("action", "")
    source = rec.get("source", "")
    email_date = rec.get("email_date", "")
    stop_loss = rec.get("stop_loss_price")
    price_target = rec.get("price_target")
    sentiment = rec.get("sentiment", "")
    instrument_type = rec.get("instrument_type", "STOCK")
    option_symbol = rec.get("option_symbol")
    option_type = rec.get("option_type")
    strike_price = rec.get("strike_price")
    expiration_date = rec.get("expiration_date")
    closed_by = rec.get("closed_by")

    lines = [f"[INBOX] {action}: {ticker} | {source}"]

    # Option details
    if instrument_type == "OPTION" and option_symbol:
        option_parts = [option_symbol]
        if option_type and strike_price:
            option_parts.append(f"{option_type} ${strike_price}")
        if expiration_date:
            option_parts.append(f"exp {expiration_date}")
        lines.append(f"Option: {' | '.join(option_parts)}")

    if stop_loss:
        lines.append(f"Stop: ${stop_loss}")
    if price_target:
        lines.append(f"Target: ${price_target}")
    if sentiment:
        lines.append(f'"{sentiment}"')
    lines.append(email_date)

    # For close actions, show who originally recommended it and when
    if action in CLOSE_ACTIONS:
        if closed_by:
            lines.append(f"Closed by: {closed_by}")
        if open_position:
            first_rec = open_position.get("first_rec_date")
            if first_rec:
                lines.append(f"Orig rec: {first_rec}")

    return "\n".join(lines)


def _send_sms(phone_number: str, message: str) -> None:
    kwargs = dict(
        PhoneNumber=phone_number,
        Message=message,
        MessageAttributes={
            "AWS.SNS.SMS.SMSType": {
                "DataType": "String",
                "StringValue": "Transactional",
            }
        },
    )
    if ORIGINATION_NUMBER:
        kwargs["MessageAttributes"]["AWS.MM.SMS.OriginationNumber"] = {
            "DataType": "String",
            "StringValue": ORIGINATION_NUMBER,
        }
    sns.publish(**kwargs)


def _send_pushover(user_key: str, title: str, message: str) -> None:
    data = urllib.parse.urlencode({
        "token": PUSHOVER_API_TOKEN,
        "user": user_key,
        "title": title,
        "message": message,
    }).encode()
    req = urllib.request.Request("https://api.pushover.net/1/messages.json", data=data)
    urllib.request.urlopen(req, timeout=10)


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
        action = rec.get("action", "").upper()
        subject = rec.get("email_subject", "")
        source = rec.get("source", "")
        if not ticker:
            continue

        subject_lower = subject.lower()
        source_lower = source.lower()
        urgent_trigger = (
            "urgent" in subject_lower
            or "income matrix" in subject_lower
            or "zach scheidt" in source_lower
        )

        # Immediate dispatch for actionable/urgent recommendations.
        immediate_actions = {"BUY", "SELL", "STOP_LOSS", "CLOSE", "POSITIVE", "NEGATIVE", "HOLD"}
        if action not in immediate_actions and not urgent_trigger:
            logger.info("ticker=%s action=%s not configured for immediate alert.", ticker, action)
            continue

        # For close actions, fetch original rec date from OpenPositions
        open_position = None
        if action in CLOSE_ACTIONS:
            open_position = _get_open_position(ticker, rec.get("source", ""))

        message = _format_sms(rec, open_position)
        logger.info("Sending immediate alert for ticker=%s to %d subscribers", ticker, len(subscribers))

        for subscriber in subscribers:
            phone = subscriber["PK"].removeprefix("SUBSCRIBER#")
            pushover_user_key = subscriber.get("pushover_user_key", "")
            if phone.startswith("+"):
                try:
                    _send_sms(phone, message[:320])
                    logger.info("SMS sent to %s for ticker=%s", phone, ticker)
                except Exception as exc:
                    logger.error("Failed to send SMS to %s: %s", phone, exc)
            if pushover_user_key and PUSHOVER_API_TOKEN:
                try:
                    _send_pushover(pushover_user_key, f"[INBOX] {ticker} {rec.get('action', '')}", message)
                    logger.info("Pushover sent to %s for ticker=%s", pushover_user_key, ticker)
                except Exception as exc:
                    logger.error("Failed to send Pushover to %s: %s", pushover_user_key, exc)
