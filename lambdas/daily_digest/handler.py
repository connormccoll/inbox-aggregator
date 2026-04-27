"""
daily_digest/handler.py

EventBridge-triggered Lambda. Runs weekdays after market close.
Queries today's Recommendations from DynamoDB DateIndex GSI,
assembles a plain-text digest, and sends it to all active subscribers.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)
sns = boto3.client("sns", region_name=region)

RECOMMENDATIONS_TABLE = os.environ["RECOMMENDATIONS_TABLE"]
SUBSCRIBERS_TABLE = os.environ["SUBSCRIBERS_TABLE"]

# Ordering preference for digest sections
ACTION_ORDER = ["STOP_LOSS", "SELL", "BUY", "HOLD", "POSITIVE", "NEGATIVE"]


def _get_todays_recommendations(date_str: str) -> list[dict]:
    table = dynamodb.Table(RECOMMENDATIONS_TABLE)
    resp = table.query(
        IndexName="DateIndex",
        KeyConditionExpression=Key("date_pk").eq(f"DATE#{date_str}"),
    )
    return resp.get("Items", [])


def _get_active_subscribers() -> list[dict]:
    table = dynamodb.Table(SUBSCRIBERS_TABLE)
    resp = table.query(
        IndexName="StatusIndex",
        KeyConditionExpression=Key("status").eq("ACTIVE"),
    )
    return resp.get("Items", [])


def _build_digest(date_str: str, recommendations: list[dict]) -> str:
    if not recommendations:
        return f"[INBOX] Digest {date_str}\nNo recommendations found today."

    # Group by action
    by_action: dict[str, list[str]] = {}
    for rec in recommendations:
        action = rec.get("action", "OTHER")
        ticker = rec.get("ticker", "?")
        source = rec.get("source", "")
        label = f"{ticker} ({source})" if source else ticker
        by_action.setdefault(action, []).append(label)

    lines = [f"[INBOX] Digest {date_str}"]

    for action in ACTION_ORDER:
        if action in by_action:
            tickers_str = ", ".join(by_action[action])
            lines.append(f"{action}: {tickers_str}")

    # Any unexpected action types
    for action, tickers in by_action.items():
        if action not in ACTION_ORDER:
            lines.append(f"{action}: {', '.join(tickers)}")

    return "\n".join(lines)


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


def lambda_handler(event: dict, context) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info("Running daily digest for date=%s", today)

    recommendations = _get_todays_recommendations(today)
    logger.info("Found %d recommendations for %s", len(recommendations), today)

    subscribers = _get_active_subscribers()
    if not subscribers:
        logger.info("No active subscribers — digest not sent.")
        return

    digest = _build_digest(today, recommendations)
    logger.info("Digest message:\n%s", digest)

    for subscriber in subscribers:
        phone = subscriber["PK"].removeprefix("SUBSCRIBER#")
        try:
            _send_sms(phone, digest)
            logger.info("Digest SMS sent to %s", phone)
        except Exception as exc:
            logger.error("Failed to send digest to %s: %s", phone, exc)
