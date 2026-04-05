"""
gmail_watch_refresh/handler.py

EventBridge rate(1 day) Lambda.
Renews the Gmail push notification watch, which expires every 7 days.
Calling watch() on an already-watched mailbox resets the expiration.
"""

import json
import logging
import os

import boto3
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
GCP_TOPIC_NAME = os.environ["GCP_TOPIC_NAME"]
GMAIL_SECRET_NAME = os.environ["GMAIL_SECRET_NAME"]


def _build_gmail_service():
    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=GMAIL_SECRET_NAME)
    creds_data = json.loads(resp["SecretString"])

    credentials = Credentials(
        token=None,
        refresh_token=creds_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def lambda_handler(event: dict, context) -> dict:
    logger.info("Renewing Gmail Watch. Topic: %s", GCP_TOPIC_NAME)

    service = _build_gmail_service()

    response = (
        service.users()
        .watch(
            userId="me",
            body={
                "topicName": GCP_TOPIC_NAME,
                "labelIds": ["INBOX"],
                "labelFilterBehavior": "INCLUDE",
            },
        )
        .execute()
    )

    history_id = response.get("historyId")
    expiration = response.get("expiration")

    logger.info(
        "Gmail Watch renewed. historyId=%s expiration=%s",
        history_id,
        expiration,
    )

    return {
        "status": "ok",
        "historyId": history_id,
        "expiration": expiration,
    }
