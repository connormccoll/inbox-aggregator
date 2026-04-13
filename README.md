# Inbox Aggregator

An AWS-serverless pipeline that monitors a Gmail inbox for financial newsletter and TradeSmith emails. AWS Bedrock (Claude Haiku) extracts stock signals and portfolio holdings. Immediate SMS fires via AWS SNS when a signal involves an owned ticker; a daily end-of-day digest goes to all subscribers.

## Architecture

```
Gmail Inbox
  └─ Gmail Watch ──► Google Cloud Pub/Sub (push subscription)
                               │
                               ▼
                    API Gateway /gmail-push
                               │
                               ▼
                    Lambda: gmail-webhook
                    (history.list → enqueue message IDs)
                               │
                               ▼
                    SQS: email-processing-queue
                               │
                               ▼
                    Lambda: email-processor
                    ├─ Gmail API: fetch full email
                    ├─ DynamoDB atomic dedup
                    ├─ Bedrock Claude Haiku: JSON extraction
                    │   (tickers, actions, sentiment, portfolio)
                    ├─ Write ──► Recommendations table
                    └─ Write ──► Holdings table

  DynamoDB Streams (Recommendations, INSERT only)
                               │
                               ▼
                    Lambda: sns-dispatcher
                    ├─ Holdings TickerIndex GSI: is ticker owned?
                    └─ If yes ──► SNS SMS to all active subscribers

  EventBridge cron (weekdays 9:30 PM UTC ≈ 4:30 PM EST)
                               │
                               ▼
                    Lambda: daily-digest
                    └─ DateIndex GSI → digest SMS to all subscribers

  EventBridge rate (1 day)
                               │
                               ▼
                    Lambda: gmail-watch-refresh
                    └─ Renews gmail.users.watch() (expires every 7 days)
```

## DynamoDB Tables

| Table | PK | SK | Key GSIs |
|---|---|---|---|
| Recommendations | `TICKER#<ticker>` | `<YYYY-MM-DD>#<message_id>` | DateIndex (date→ticker) |
| Holdings | `PORTFOLIO#<name>` | `TICKER#<ticker>` | TickerIndex (ticker→portfolio) |
| Subscribers | `SUBSCRIBER#<phone>` | — | StatusIndex (status→phone) |
| ProcessedEmails | `<message_id>` | — | — |

## Prerequisites (One-Time Manual Setup)

All manual steps must be completed before the first deployment.
The S3 state bucket is **created automatically by the pipeline** on first run — no manual bucket creation needed.

### 1. AWS — OIDC Provider + GitHub Actions IAM Role

```bash
# Create OIDC provider
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# Create a role with the trust policy in docs/oidc-trust-policy.json
# Replace ACCOUNT_ID with your AWS account ID
aws iam create-role \
  --role-name inbox-aggregator-github-actions \
  --assume-role-policy-document file://docs/oidc-trust-policy.json

# Attach required permissions (AdministratorAccess for initial deploy; tighten after)
aws iam attach-role-policy \
  --role-name inbox-aggregator-github-actions \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
```

Note the role ARN — you'll add it as the `AWS_ROLE_ARN` GitHub Secret.

### 3. GCP — Pub/Sub Project

1. Create a GCP project at https://console.cloud.google.com
2. Enable the Pub/Sub API
3. Create a service account with `roles/pubsub.admin` + `roles/iam.serviceAccountAdmin`
4. Download a JSON key for that service account
5. Add the key contents as the `GCP_CREDENTIALS` GitHub Secret
6. Add the project ID as the `GCP_PROJECT_ID` GitHub Variable

### 4. Gmail OAuth — Refresh Token

Register an OAuth 2.0 client in Google Cloud Console (same project as above):
- Application type: Desktop
- Scopes: `https://www.googleapis.com/auth/gmail.readonly`

Download the client secret JSON, then run:

```bash
pip install google-auth-oauthlib boto3
python scripts/setup_gmail_oauth.py \
  --client-secret-file path/to/client_secret.json \
  --region us-east-1
```

This performs the OAuth consent flow and stores the credentials in AWS Secrets Manager at `inbox-aggregator/gmail`.

### 5. AWS Bedrock — Enable Model Access

In the AWS Console → Bedrock → Model access, request access for:
- **Anthropic Claude Haiku 4.5** (`anthropic.claude-haiku-4-5-20251001-v1:0`) in `us-east-1`

Access is typically granted within minutes.

### 6. AWS SNS — Request SMS Production Access

New AWS accounts start in the SMS sandbox (can only send to verified numbers).
- Console → SNS → Text messaging (SMS) → Sandbox destination phone numbers: add and verify subscriber numbers for testing
- To go production: SNS → Text messaging → Account → Request production access

### 7. GitHub — Secrets and Variables

**Secrets** (sensitive — never logged):
| Name | Value |
|---|---|
| `AWS_ROLE_ARN` | ARN of the IAM role created in step 2 |
| `GCP_CREDENTIALS` | Contents of the GCP service account JSON key |

**Variables** (non-sensitive — visible in workflow logs):
| Name | Value |
|---|---|
| `AWS_REGION` | `us-east-1` |
| `GCP_PROJECT_ID` | Your GCP project ID |
| `BEDROCK_MODEL_ID` | `anthropic.claude-haiku-4-5-20251001-v1:0` |
| `TF_STATE_BUCKET` | `inbox-aggregator-tf-state` |
| `DAILY_DIGEST_CRON` | `cron(30 21 ? * MON-FRI *)` |

## Deployment

```bash
# On any PR to main:
# GitHub Actions runs terraform plan and comments the output on the PR.

# On merge to main:
# GitHub Actions runs terraform apply automatically.
```

## Adding Subscribers

Subscribers are managed directly in DynamoDB. Add an item to the `inbox-aggregator-subscribers` table:

```json
{
  "PK": "SUBSCRIBER#+15551234567",
  "status": "ACTIVE",
  "name": "Your Name",
  "created_at": "2026-04-05T00:00:00Z"
}
```

Phone number must be in E.164 format (e.g. `+15551234567`).

## Project Layout

```
├── .github/workflows/
│   ├── pr-check.yml       # terraform plan on PRs
│   └── deploy.yml         # terraform apply on main
├── terraform/
│   ├── backend.tf
│   ├── providers.tf
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── modules/
│       ├── dynamodb/
│       ├── lambda/
│       ├── api_gateway/
│       ├── sqs/
│       ├── eventbridge/
│       ├── secrets/
│       └── pubsub/
├── lambdas/
│   ├── layer/requirements.txt
│   ├── gmail_webhook/handler.py
│   ├── email_processor/handler.py
│   ├── sns_dispatcher/handler.py
│   ├── daily_digest/handler.py
│   └── gmail_watch_refresh/handler.py
├── scripts/
│   ├── bootstrap.sh
│   └── setup_gmail_oauth.py
└── docs/
    └── oidc-trust-policy.json
```
