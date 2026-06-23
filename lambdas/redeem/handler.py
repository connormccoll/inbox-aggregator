"""
redeem/handler.py

API Gateway Lambda (Cognito-authorized). POST /redeem.

A user who has just signed in with Google is authenticated but not yet
authorized. They submit the shared invitation password here; on success we:
  1. add them to the Cognito "active" group (the API authorizer requires it), and
  2. create their PROFILE row in the Users table.

The user must obtain a fresh token afterwards for the new group claim to appear.
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)
cognito = boto3.client("cognito-idp", region_name=region)

USERS_TABLE = os.environ["USERS_TABLE"]
USER_POOL_ID = os.environ["USER_POOL_ID"]
INVITATION_PASSWORD = os.environ["INVITATION_PASSWORD"]
ACTIVE_GROUP = os.environ.get("ACTIVE_GROUP", "active")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _claims(event: dict) -> dict:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    ) or {}


def lambda_handler(event: dict, context) -> dict:
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    if event.get("httpMethod") != "POST":
        return _response(405, {"error": "Method not allowed"})

    claims = _claims(event)
    sub = claims.get("sub")
    username = claims.get("cognito:username") or sub
    email = claims.get("email", "")
    name = claims.get("name", "")
    if not sub or not username:
        return _response(401, {"error": "Unauthenticated"})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    if body.get("password") != INVITATION_PASSWORD:
        logger.warning("Invalid invitation password from sub=%s", sub)
        return _response(403, {"error": "Invalid invitation password"})

    # 1. Add to the active group (idempotent).
    try:
        cognito.admin_add_user_to_group(
            UserPoolId=USER_POOL_ID,
            Username=username,
            GroupName=ACTIVE_GROUP,
        )
    except Exception as exc:
        logger.exception("Failed to add user to group: %s", exc)
        return _response(500, {"error": "Could not activate account"})

    # 2. Upsert the profile row.
    dynamodb.Table(USERS_TABLE).put_item(
        Item={
            "PK": f"USER#{sub}",
            "SK": "PROFILE",
            "email": email,
            "name": name,
            "status": "ACTIVE",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    logger.info("Activated user sub=%s email=%s", sub, email)

    return _response(200, {
        "message": "Invitation redeemed. Refresh your session to finish signing in.",
    })
