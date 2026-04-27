# Inbox Aggregator

An AWS-serverless pipeline that monitors a Gmail inbox for financial newsletter and TradeSmith emails. AWS Bedrock (Claude Haiku) extracts stock signals and portfolio holdings. Immediate SMS fires via AWS SNS when a signal involves an owned ticker; a daily end-of-day digest and a weekly open-positions summary go to all subscribers.

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
                    ├─ Upsert ──► OpenPositions table  (OPEN/CLOSED per ticker+source)
                    ├─ Write  ──► Recommendations table
                    └─ Write  ──► Holdings table (if portfolio data in email)

  DynamoDB Streams (Recommendations, INSERT only)
                               │
                               ▼
                    Lambda: sns-dispatcher
                    ├─ Holdings TickerIndex GSI: is ticker owned?
                    ├─ If SELL/STOP_LOSS: fetch OpenPositions for original rec date
                    └─ If owned ──► SNS SMS to all active subscribers

  EventBridge cron (weekdays 9:30 PM UTC ≈ 4:30 PM EST)
                               │
                               ▼
                    Lambda: daily-digest
                    └─ DateIndex GSI → today's recs → digest SMS to all subscribers

  EventBridge cron (Sundays 7 PM UTC)
                               │
                               ▼
                    Lambda: weekly-digest
                    └─ Scan OpenPositions → full open/close summary SMS to all subscribers

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
| OpenPositions | `TICKER#<ticker>` | `SOURCE#<source>` | — |
| Subscribers | `SUBSCRIBER#<phone>` | — | StatusIndex (status→phone) |
| ProcessedEmails | `<message_id>` | — | — |

**OpenPositions** tracks one row per ticker+source. `open_status=OPEN` means the source currently recommends holding. `open_status=CLOSED` (SELL/STOP_LOSS signal) has a 7-day TTL so it stays visible in the weekly digest for a week then auto-purges.

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
| `WEEKLY_DIGEST_CRON` | `cron(0 19 ? * SUN *)` (optional — this is the default) |

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

On Windows PowerShell (avoids quote-stripping issues):

```powershell
@'
{"PK": {"S": "SUBSCRIBER#+15551234567"}, "status": {"S": "ACTIVE"}, "name": {"S": "Your Name"}}
'@ | Out-File -Encoding ascii subscriber.json
aws dynamodb put-item --table-name inbox-aggregator-subscribers --region us-east-1 --item file://subscriber.json
Remove-Item subscriber.json
```

## Adding Holdings (Owned Positions)

Holdings drive **immediate SMS alerts** — if a ticker is not in Holdings, no real-time alert fires (it still appears in the daily/weekly digest). Holdings can be populated two ways:

**Automatically:** if a newsletter email contains a portfolio listing, Bedrock extracts it and the `email-processor` Lambda upserts it into Holdings.

**Manually via CLI:**

```powershell
@'
{"PK": {"S": "PORTFOLIO#Main"}, "SK": {"S": "TICKER#AAPL"}, "ticker_pk": {"S": "TICKER#AAPL"}, "portfolio_sk": {"S": "PORTFOLIO#Main"}, "ticker": {"S": "AAPL"}, "portfolio_name": {"S": "Main"}, "shares": {"S": "50"}}
'@ | Out-File -Encoding ascii holding.json
aws dynamodb put-item --table-name inbox-aggregator-holdings --region us-east-1 --item file://holding.json
Remove-Item holding.json
```

Repeat for each position. The `portfolio_name` groups positions (e.g. `Main`, `Growth`, `IRA`).

## Alert and Digest Behaviour

### Immediate SMS (real-time)

Fires only when a **newly extracted recommendation's ticker exists in Holdings**. Sent within seconds of the email arriving.

Example for a BUY signal:
```
[INBOX] BUY: AAPL | TradeSmith
Target: $225
Portfolio: Main (50 shares)
2026-04-27
```

Example for a STOP_LOSS on an owned position (includes original rec date):
```
[INBOX] STOP_LOSS: TSLA | TradeSmith
Stop: $210
Portfolio: Main (30 shares)
2026-04-27
Orig rec: 2026-03-15
```

### Daily Digest (weekdays ~4:30 PM ET)

Covers **everything extracted that day** regardless of whether you own the ticker. Grouped by action type, ordered by urgency (STOP_LOSS first, then SELL, BUY, HOLD, etc.):

```
[INBOX] Digest 2026-04-27
STOP_LOSS: TSLA (TradeSmith)
SELL: META (Motley Fool)
BUY: NVDA (TradeSmith), AAPL (Seeking Alpha)
POSITIVE: MSFT (Motley Fool)
```

### Weekly Digest (Sundays ~3 PM ET)

Scans the OpenPositions table — one row per ticker+source, built up over time. Shows the full picture of all active recommendations with source, action, confidence, and original date. Owned tickers (`*`) sort to the top. Close alerts for owned positions stay visible for 7 days after the signal.

```
[INBOX] Weekly Summary — 2026-04-27

OPEN RECOMMENDATIONS:
*AAPL: TradeSmith/BUY/HIG since 2026-04-01 | Motley Fool/POSITIVE/MED since 2026-04-10
*TSLA: TradeSmith/BUY/HIG since 2026-03-15
 NVDA: Seeking Alpha/BUY/MED since 2026-04-20

CLOSE ALERTS (owned positions):
*TSLA STOP_LOSS by TradeSmith on 2026-04-25 (rec'd since 2026-03-15)

Total: 4 open recs across 3 tickers. * = owned position.
```

Long digests are automatically split into numbered SMS chunks `[1]`, `[2]`, etc.

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
│   ├── weekly_digest/handler.py
│   └── gmail_watch_refresh/handler.py
├── scripts/
│   ├── bootstrap.sh
│   └── setup_gmail_oauth.py
└── docs/
    └── oidc-trust-policy.json
```
