"""
notify.py

Shared delivery helpers. Copied into each Lambda that fans out notifications
(mirrors the gmail_client.py "copy shared first-party code" convention).
Stdlib + boto3 only — no Lambda layer required.

SMS is a graceful no-op until an SNS origination number is configured: send_sms
logs and returns False instead of raising, so the rest of a broadcast still goes
out over Pushover. Once ORIGINATION_NUMBER is set, SMS starts flowing with no
code change.
"""

import logging
import urllib.parse
import urllib.request

from boto3.dynamodb.conditions import Key

logger = logging.getLogger()

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


def get_active_channels(table) -> list[dict]:
    """Return every active delivery channel across all users via the GSI."""
    items: list[dict] = []
    kwargs = {
        "IndexName": "ActiveChannels",
        "KeyConditionExpression": Key("channel_status").eq("ACTIVE"),
    }
    resp = table.query(**kwargs)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.query(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
        items.extend(resp.get("Items", []))
    return items


def send_sms(sns, phone: str, message: str, origination_number: str = "") -> bool:
    """Send an SMS. Returns False (no-op) when no origination number is set."""
    if not origination_number:
        logger.info("SMS skipped (no origination number configured): to=%s", phone)
        return False
    sns.publish(
        PhoneNumber=phone,
        Message=message,
        MessageAttributes={
            "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"},
            "AWS.MM.SMS.OriginationNumber": {"DataType": "String", "StringValue": origination_number},
        },
    )
    return True


def send_pushover(token: str, user_key: str, title: str, message: str) -> None:
    data = urllib.parse.urlencode({
        "token": token,
        "user": user_key,
        "title": title,
        "message": message[:1024],
    }).encode()
    req = urllib.request.Request(PUSHOVER_URL, data=data)
    urllib.request.urlopen(req, timeout=10)


def dispatch(
    channels: list[dict],
    sns,
    *,
    sms_message: str,
    pushover_title: str,
    pushover_message: str,
    origination_number: str = "",
    pushover_token: str = "",
) -> None:
    """Fan a single broadcast out to a list of active channel rows."""
    for ch in channels:
        ctype = ch.get("channel_type", "")
        value = ch.get("value", "")
        if not value:
            continue
        try:
            if ctype == "SMS":
                send_sms(sns, value, sms_message, origination_number)
            elif ctype == "PUSHOVER" and pushover_token:
                send_pushover(pushover_token, value, pushover_title, pushover_message)
        except Exception as exc:
            logger.error("Delivery failed type=%s value=%s: %s", ctype, value, exc)
