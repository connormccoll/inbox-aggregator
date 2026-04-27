"""
gmail_webhook/handler.py

Receives Google Cloud Pub/Sub push notifications, decodes the payload,
calls Gmail history.list to enumerate new message IDs, and enqueues
each unprocessed message ID to SQS for the email-processor Lambda.

Responds with HTTP 200 to acknowledge the Pub/Sub message.
"""

import base64
import json
import logging
import os

import boto3

from gmail_client import build_gmail_service

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sqs = boto3.client("sqs", region_name=os.environ["AWS_REGION_NAME"])
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]

# history_id is stateful — we persist it in SSM Parameter Store so restarts
# don't re-process old emails.
ssm = boto3.client("ssm", region_name=os.environ["AWS_REGION_NAME"])
HISTORY_ID_PARAM = "/inbox-aggregator/gmail-history-id"


def _get_stored_history_id() -> str | None:
    try:
        resp = ssm.get_parameter(Name=HISTORY_ID_PARAM)
        return resp["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        return None


def _store_history_id(history_id: str) -> None:
    ssm.put_parameter(
        Name=HISTORY_ID_PARAM,
        Value=str(history_id),
        Type="String",
        Overwrite=True,
    )


def lambda_handler(event: dict, context) -> dict:
    """
    API Gateway proxy integration handler.
    """
    try:
        body = json.loads(event.get("body", "{}"))
    except (json.JSONDecodeError, TypeError):
        logger.error("Invalid JSON body")
        return {"statusCode": 400, "body": "Bad Request"}

    message = body.get("message", {})
    encoded_data = message.get("data", "")

    if not encoded_data:
        logger.warning("Pub/Sub message has no data field — acknowledging.")
        return {"statusCode": 200, "body": "OK"}

    # Decode Base64URL payload: {"emailAddress": "...", "historyId": "..."}
    try:
        decoded = base64.urlsafe_b64decode(encoded_data + "==").decode("utf-8")
        notification = json.loads(decoded)
    except Exception as exc:
        logger.error("Failed to decode Pub/Sub data: %s", exc)
        return {"statusCode": 200, "body": "OK"}  # Still ack to avoid retries

    new_history_id = str(notification.get("historyId", ""))
    if not new_history_id:
        logger.warning("No historyId in notification — skipping.")
        return {"statusCode": 200, "body": "OK"}

    stored_history_id = _get_stored_history_id()

    message_ids: list[str] = []

    if stored_history_id:
        try:
            service = build_gmail_service()
            history_response = (
                service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=stored_history_id,
                    historyTypes=["messageAdded"],
                )
                .execute()
            )

            for history_record in history_response.get("history", []):
                for added in history_record.get("messagesAdded", []):
                    msg_id = added["message"]["id"]
                    message_ids.append(msg_id)

        except Exception as exc:
            logger.error("Gmail history.list failed: %s", exc)
            # Don't fail — still update historyId to avoid getting stuck
    else:
        logger.info(
            "No stored historyId — this is the first notification. "
            "Storing new historyId and waiting for next push."
        )

    # Update stored history ID before enqueuing so we don't miss messages
    # on a Lambda retry
    _store_history_id(new_history_id)

    # Enqueue unique message IDs to SQS
    for msg_id in message_ids:
        sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps({"message_id": msg_id}),
            MessageDeduplicationId=None,  # Standard queue — no dedup needed here (handled in email_processor)
        )
        logger.info("Enqueued message_id=%s", msg_id)

    logger.info(
        "Processed notification historyId=%s; enqueued %d message(s)",
        new_history_id,
        len(message_ids),
    )

    return {"statusCode": 200, "body": "OK"}
