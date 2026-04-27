#!/usr/bin/env python3
"""
scripts/setup_gmail_oauth.py

One-time OAuth2 consent flow for the Gmail account to be monitored.
Stores client_id, client_secret, and refresh_token in AWS Secrets Manager
at the path inbox-aggregator/gmail.

Usage:
    pip install google-auth-oauthlib boto3
    python scripts/setup_gmail_oauth.py \\
        --client-secret-file path/to/client_secret.json \\
        --region us-east-1

The client_secret.json file is downloaded from Google Cloud Console:
    APIs & Services > Credentials > OAuth 2.0 Client IDs > Download JSON
    (Application type: Desktop)

IMPORTANT: Do NOT commit client_secret.json or token.json to git.
           Both are in .gitignore.
"""

import argparse
import json
import sys
from pathlib import Path

import boto3
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SECRET_NAME = "inbox-aggregator/gmail"


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up Gmail OAuth credentials in AWS Secrets Manager.")
    parser.add_argument(
        "--client-secret-file",
        required=True,
        type=Path,
        help="Path to the OAuth client secret JSON file downloaded from Google Cloud Console.",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1).",
    )
    parser.add_argument(
        "--secret-name",
        default=SECRET_NAME,
        help=f"Secrets Manager secret name (default: {SECRET_NAME}).",
    )
    args = parser.parse_args()

    client_secret_path: Path = args.client_secret_file
    if not client_secret_path.exists():
        print(f"ERROR: File not found: {client_secret_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Starting OAuth2 consent flow for scopes: {SCOPES}")
    print("A browser window will open. Sign in and grant access to the Gmail account to be monitored.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    credentials = flow.run_local_server(port=0)

    # Extract the values we need to store
    with open(client_secret_path) as f:
        client_data = json.load(f)

    # Support both "installed" and "web" client types
    client_config = client_data.get("installed") or client_data.get("web", {})

    secret_value = {
        "client_id": client_config["client_id"],
        "client_secret": client_config["client_secret"],
        "refresh_token": credentials.refresh_token,
    }

    if not secret_value["refresh_token"]:
        print("ERROR: No refresh_token received. Make sure access_type=offline in the OAuth flow.", file=sys.stderr)
        sys.exit(1)

    print(f"OAuth consent complete. Storing credentials in Secrets Manager: {args.secret_name}")

    sm = boto3.client("secretsmanager", region_name=args.region)
    try:
        sm.put_secret_value(
            SecretId=args.secret_name,
            SecretString=json.dumps(secret_value),
        )
        print(f"✓ Credentials stored in AWS Secrets Manager at '{args.secret_name}'")
    except sm.exceptions.ResourceNotFoundException:
        # Secret doesn't exist yet (hasn't been deployed via Terraform)
        print(f"Secret '{args.secret_name}' not found — creating it now.")
        sm.create_secret(
            Name=args.secret_name,
            SecretString=json.dumps(secret_value),
            Description="Gmail OAuth2 credentials for inbox-aggregator.",
        )
        print(f"✓ Created and stored credentials at '{args.secret_name}'")

    print()
    print("Next: deploy the infrastructure with Terraform, then invoke the")
    print("gmail-watch-refresh Lambda once to register the Gmail Watch.")


if __name__ == "__main__":
    main()
