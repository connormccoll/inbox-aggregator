"""
channels/handler.py

API Gateway Lambda (Cognito-authorized). Manages a single user's delivery
channels (phone numbers and Pushover keys). The user is identified by the
Cognito `sub` claim — never by anything in the request body.

    GET    /channels                                 list the caller's channels
    POST   /channels {action:"add",    type, value}  add a channel (PENDING) + start verification
    POST   /channels {action:"verify", type, value, code}  confirm a channel → ACTIVE
    DELETE /channels {type, value}                   remove a channel

A channel only joins the broadcast (channel_status = "ACTIVE" on the
ActiveChannels GSI) once it has been verified. SMS verification requires an SNS
origination number; until one is configured the channel is saved as PENDING and
the caller is told verification can't be delivered yet.
"""

import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)
sns = boto3.client("sns", region_name=region)

USERS_TABLE = os.environ["USERS_TABLE"]
ORIGINATION_NUMBER = os.environ.get("ORIGINATION_NUMBER", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
CODE_TTL_SECONDS = 15 * 60
VALID_TYPES = {"SMS", "PUSHOVER"}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
}


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _sub(event: dict) -> str | None:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
        .get("sub")
    )


def _in_active_group(event: dict) -> bool:
    """True if the caller's Cognito token carries the 'active' group claim."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    ) or {}
    raw = claims.get("cognito:groups", "")
    groups = raw if isinstance(raw, list) else str(raw).strip("[]").replace(",", " ").split()
    return "active" in groups


def _channel_sk(ctype: str, value: str) -> str:
    return f"CHANNEL#{ctype}#{value}"


def _public_view(item: dict) -> dict:
    """Strip internal/verification fields before returning to the client."""
    return {
        "type": item.get("channel_type"),
        "value": item.get("value"),
        "verified": bool(item.get("verified", False)),
        "opt_in": bool(item.get("opt_in", True)),
        "status": "ACTIVE" if item.get("channel_status") == "ACTIVE" else "PENDING",
        "created_at": item.get("created_at"),
    }


def _list_channels(table, sub: str) -> dict:
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{sub}") & Key("SK").begins_with("CHANNEL#"),
    )
    return _response(200, {"channels": [_public_view(i) for i in resp.get("Items", [])]})


def _add_channel(table, sub: str, ctype: str, value: str) -> dict:
    if ctype == "SMS":
        if not E164_RE.match(value):
            return _response(400, {"error": "Phone must be E.164, e.g. +12125551234"})
    elif ctype == "PUSHOVER":
        if not (5 <= len(value) <= 64):
            return _response(400, {"error": "Invalid Pushover user key"})

    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(timezone.utc).isoformat()
    table.put_item(
        Item={
            "PK": f"USER#{sub}",
            "SK": _channel_sk(ctype, value),
            "channel_type": ctype,
            "value": value,
            "verified": False,
            "opt_in": True,
            "verification_code": code,
            "verification_expires": int(time.time()) + CODE_TTL_SECONDS,
            "created_at": now,
        }
    )

    # Deliver the verification code over the channel being verified.
    if ctype == "PUSHOVER" and PUSHOVER_API_TOKEN:
        try:
            notify.send_pushover(PUSHOVER_API_TOKEN, value, "Inbox Aggregator verification",
                                 f"Your verification code is {code}")
        except Exception as exc:
            logger.error("Failed to send Pushover verification: %s", exc)
            return _response(502, {"error": "Could not send verification push. Check the user key."})
        return _response(201, {"message": "Verification code sent via Pushover. Enter it to activate.",
                               "channel": _public_view({"channel_type": ctype, "value": value})})

    if ctype == "SMS":
        sent = notify.send_sms(sns, value, f"Inbox Aggregator code: {code}", ORIGINATION_NUMBER)
        if not sent:
            return _response(202, {
                "message": "Channel saved, but SMS verification is unavailable until an "
                           "origination number is configured. It will stay pending.",
                "channel": _public_view({"channel_type": ctype, "value": value}),
            })
        return _response(201, {"message": "Verification code sent via SMS. Enter it to activate.",
                               "channel": _public_view({"channel_type": ctype, "value": value})})

    return _response(400, {"error": "Unsupported channel type"})


def _verify_channel(table, sub: str, ctype: str, value: str, code: str) -> dict:
    key = {"PK": f"USER#{sub}", "SK": _channel_sk(ctype, value)}
    item = table.get_item(Key=key).get("Item")
    if not item:
        return _response(404, {"error": "Channel not found"})
    if item.get("verified"):
        return _response(200, {"message": "Already verified", "channel": _public_view(item)})

    if str(code).strip() != str(item.get("verification_code", "")):
        return _response(403, {"error": "Incorrect code"})
    if int(time.time()) > int(item.get("verification_expires", 0)):
        return _response(403, {"error": "Code expired — request a new one"})

    table.update_item(
        Key=key,
        UpdateExpression=(
            "SET verified = :t, channel_status = :active, verified_at = :now "
            "REMOVE verification_code, verification_expires"
        ),
        ExpressionAttributeValues={
            ":t": True,
            ":active": "ACTIVE",
            ":now": datetime.now(timezone.utc).isoformat(),
        },
    )
    logger.info("Channel verified sub=%s type=%s", sub, ctype)
    return _response(200, {"message": "Channel verified and active."})


def _delete_channel(table, sub: str, ctype: str, value: str) -> dict:
    table.delete_item(Key={"PK": f"USER#{sub}", "SK": _channel_sk(ctype, value)})
    return _response(200, {"message": "Channel removed."})


def lambda_handler(event: dict, context) -> dict:
    method = event.get("httpMethod")
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    sub = _sub(event)
    if not sub:
        return _response(401, {"error": "Unauthenticated"})
    if not _in_active_group(event):
        return _response(403, {"error": "Account not activated \u2014 redeem your invitation first."})

    table = dynamodb.Table(USERS_TABLE)

    if method == "GET":
        return _list_channels(table, sub)

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    ctype = str(body.get("type", "")).upper().strip()
    value = str(body.get("value", "")).strip()
    if ctype not in VALID_TYPES:
        return _response(400, {"error": f"type must be one of {sorted(VALID_TYPES)}"})
    if not value:
        return _response(400, {"error": "value is required"})

    if method == "DELETE":
        return _delete_channel(table, sub, ctype, value)

    if method == "POST":
        action = str(body.get("action", "add")).lower()
        if action == "add":
            return _add_channel(table, sub, ctype, value)
        if action == "verify":
            code = str(body.get("code", "")).strip()
            if not code:
                return _response(400, {"error": "code is required"})
            return _verify_channel(table, sub, ctype, value, code)
        return _response(400, {"error": "action must be 'add' or 'verify'"})

    return _response(405, {"error": "Method not allowed"})
