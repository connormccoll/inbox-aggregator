"""
subscribe/handler.py

API Gateway Lambda for subscriber self-registration.
POST /subscribe — validates invitation password and writes to DynamoDB Subscribers table.
OPTIONS /subscribe — returns CORS headers for browser preflight.
"""

import json
import logging
import os
import re

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)

SUBSCRIBERS_TABLE = os.environ["SUBSCRIBERS_TABLE"]
INVITATION_PASSWORD = os.environ.get("INVITATION_PASSWORD", "blackfamilytrust")

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

    return _response(200, {"message": "Successfully subscribed!"})
