"""
subscribe/handler.py

API Gateway Lambda for subscriber self-registration.
POST /subscribe — validates invitation password and writes to DynamoDB Subscribers table,
                  then sends a welcome message via SMS and/or Pushover.
OPTIONS /subscribe — returns CORS headers for browser preflight.
"""

import json
import logging
import os
import re
import urllib.parse
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)
sns = boto3.client("sns", region_name=region)

SUBSCRIBERS_TABLE = os.environ["SUBSCRIBERS_TABLE"]
INVITATION_PASSWORD = os.environ.get("INVITATION_PASSWORD", "blackfamilytrust")
ORIGINATION_NUMBER = os.environ.get("ORIGINATION_NUMBER", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _send_welcome_sms(phone: str, name: str) -> None:
    message = (
        f"Welcome to Inbox Aggregator, {name}! "
        "You'll receive stock alert notifications here. "
        "Reply STOP to unsubscribe at any time."
    )
    kwargs = dict(
        PhoneNumber=phone,
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


def _send_welcome_pushover(user_key: str, name: str) -> None:
    data = urllib.parse.urlencode({
        "token": PUSHOVER_API_TOKEN,
        "user": user_key,
        "title": "Welcome to Inbox Aggregator",
        "message": (
            f"Hi {name}! You're subscribed to Inbox Aggregator. "
            "You'll receive immediate alerts when a tracked ticker appears in your portfolio, "
            "plus daily and weekly digests."
        ),
    }).encode()
    req = urllib.request.Request("https://api.pushover.net/1/messages.json", data=data)
    urllib.request.urlopen(req, timeout=10)


def lambda_handler(event: dict, context) -> dict:
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    if event.get("httpMethod") != "POST":
        return _response(405, {"error": "Method not allowed"})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    # Validate invitation password
    if body.get("password") != INVITATION_PASSWORD:
        logger.warning("Invalid invitation password attempt")
        return _response(403, {"error": "Invalid invitation password"})

    # Validate required fields
    name = (body.get("name") or "").strip()
    phone = (body.get("phone") or "").strip()
    pushover_user_key = (body.get("pushoverUserKey") or "").strip()
    email = (body.get("email") or "").strip()

    if not name:
        return _response(400, {"error": "Name is required"})
    if not phone:
        return _response(400, {"error": "Phone number is required"})
    if not E164_RE.match(phone):
        return _response(400, {"error": "Phone must be in E.164 format (e.g. +12125551234)"})

    item = {
        "PK": f"SUBSCRIBER#{phone}",
        "status": "ACTIVE",
        "name": name,
        "phone": phone,
        "sms_opt_in": True,
    }
    if pushover_user_key:
        item["pushover_user_key"] = pushover_user_key
    if email:
        item["email"] = email

    dynamodb.Table(SUBSCRIBERS_TABLE).put_item(Item=item)
    logger.info("Subscriber registered: phone=%s name=%s", phone, name)

    # Send welcome messages — log failures but don't fail the registration
    if phone.startswith("+"):
        try:
            _send_welcome_sms(phone, name)
            logger.info("Welcome SMS sent to %s", phone)
        except Exception as exc:
            logger.error("Failed to send welcome SMS to %s: %s", phone, exc)

    if pushover_user_key and PUSHOVER_API_TOKEN:
        try:
            _send_welcome_pushover(pushover_user_key, name)
            logger.info("Welcome Pushover sent to %s", pushover_user_key)
        except Exception as exc:
            logger.error("Failed to send welcome Pushover to %s: %s", pushover_user_key, exc)

    return _response(200, {"message": "Successfully subscribed!"})
