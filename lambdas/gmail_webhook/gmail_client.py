"""
gmail_client.py

Shared helper: builds an authenticated Gmail API service using
OAuth2 credentials stored in AWS Secrets Manager.
"""

import json
import os

import boto3
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_gmail_service = None  # Module-level cache — reused across Lambda invocations


def _get_gmail_credentials() -> Credentials:
    secret_name = os.environ["GMAIL_SECRET_NAME"]
    region = os.environ["AWS_REGION_NAME"]

    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_name)
    creds_data = json.loads(resp["SecretString"])

    return Credentials(
        token=None,
        refresh_token=creds_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


def build_gmail_service():
    global _gmail_service
    if _gmail_service is None:
        credentials = _get_gmail_credentials()
        _gmail_service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    return _gmail_service
