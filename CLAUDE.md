# Inbox Aggregator — Claude Instructions

## Project Overview

Fully serverless AWS pipeline that monitors a Gmail inbox for financial newsletter emails. AWS Bedrock (Claude Haiku) extracts stock signals; subscribers receive real-time Pushover push notifications and/or SMS alerts when a tracked ticker fires, plus daily and weekly digest summaries.

## Key Facts

- **AWS account:** `317605985779`, region `us-east-1`
- **GCP project:** `inbox-aggregator-493201`
- **Default branch:** `main`
- **GitHub repo:** `connormccoll/inbox-aggregator`
- **Bedrock model:** `anthropic.claude-haiku-4-5-20251001-v1:0`
- **Python runtime:** 3.12 (all Lambdas)
- **Terraform version:** ~1.9
- **Deploy:** push to `main` → GitHub Actions runs `terraform apply`; PRs get `terraform plan` posted as a comment

## Repository Structure

```
lambdas/           Python Lambda handlers (one folder per function)
  layer/           Shared Lambda layer — requirements.txt only
  email_processor/ SQS-triggered; Gmail fetch → Bedrock extraction → DynamoDB writes
  gmail_webhook/   API Gateway-triggered; Gmail history → SQS enqueue
  gmail_watch_refresh/ EventBridge daily; renews Gmail Watch subscription
  sns_dispatcher/  DynamoDB Streams consumer; fires Pushover + SMS alerts
  subscribe/       API Gateway-triggered; subscriber self-registration
  daily_digest/    EventBridge weekday cron; sends daily rec summary
  weekly_digest/   EventBridge Sunday cron; sends full open-positions summary
  graphql_query/   GraphQL query handler
terraform/         All infrastructure as code
  main.tf          Root module; wires together all child modules
  modules/         api_gateway, dynamodb, eventbridge, lambda, pubsub, secrets, sqs
.github/workflows/ CI/CD — pr-check.yml (plan) and deploy on merge
frontend/          React + Vite subscriber registration portal (S3 + CloudFront)
scripts/           bootstrap.sh, setup_gmail_oauth.py
docs/              oidc-trust-policy.json
```

## Architecture Flow

1. Gmail Watch → GCP Pub/Sub → API Gateway `/gmail-push` → `gmail_webhook` Lambda → SQS
2. SQS → `email_processor` Lambda → Gmail API → Bedrock extraction → DynamoDB (`Recommendations`, `OpenPositions`, `Holdings`)
3. DynamoDB Streams (Recommendations INSERT) → `sns_dispatcher` → Pushover + SMS to active subscribers if ticker is in Holdings
4. EventBridge crons → `daily_digest` (weekdays 4:30 PM ET) and `weekly_digest` (Sundays 3 PM ET)

## DynamoDB Tables

| Table | PK | SK | Notable GSIs |
|---|---|---|---|
| `inbox-aggregator-recommendations` | `TICKER#<ticker>` | `<YYYY-MM-DD>#<message_id>` | DateIndex |
| `inbox-aggregator-holdings` | `PORTFOLIO#<name>` | `TICKER#<ticker>` | TickerIndex |
| `inbox-aggregator-open-positions` | `TICKER#<ticker>` | `SOURCE#<source>` | — |
| `inbox-aggregator-subscribers` | `SUBSCRIBER#<phone>` | — | StatusIndex |
| `inbox-aggregator-processed-emails` | `<message_id>` | — | — |

## Lambda Environment Variables (common pattern)

All Lambdas receive `AWS_REGION_NAME`, table name env vars (`RECOMMENDATIONS_TABLE`, `SUBSCRIBERS_TABLE`, etc.), and secret/config vars as needed. Check each handler's `os.environ[...]` calls for the full list.

## Secrets & Config

- **`inbox-aggregator/gmail`** — AWS Secrets Manager; Gmail OAuth credentials written by `scripts/setup_gmail_oauth.py`
- **GitHub Secrets:** `AWS_ROLE_ARN`, `GCP_CREDENTIALS`, `INVITATION_PASSWORD`
- **GitHub Variables:** `AWS_REGION`, `AWS_ACCOUNT_ID`, `GCP_PROJECT_ID`, `BEDROCK_MODEL_ID`, `TF_STATE_BUCKET`, `DAILY_DIGEST_CRON`, `WEEKLY_DIGEST_CRON`

## Coding Conventions

### Python (Lambdas)
- Python 3.12; use `boto3` for all AWS SDK calls
- One `handler.py` per Lambda; shared Gmail client in `gmail_client.py` (copied into functions that need it)
- Shared third-party deps go in `lambdas/layer/requirements.txt` (deployed as a Lambda Layer)
- Stdlib-only deps do **not** need to be in the layer
- Use `os.environ["VAR"]` (not `.get()`) for required env vars to fail fast on misconfiguration
- Use `os.environ.get("VAR", "")` for optional env vars
- Log with the module-level `logger = logging.getLogger(); logger.setLevel(logging.INFO)`
- DynamoDB resource: `boto3.resource("dynamodb", region_name=region)`; client for non-resource operations
- All DynamoDB keys follow `ENTITY#value` prefix convention (e.g. `TICKER#AAPL`, `PORTFOLIO#Main`, `SUBSCRIBER#+15551234567`)
- TTLs stored as integer Unix timestamps in a `ttl` attribute

### Terraform
- Resource naming: `${local.prefix}-<resource>` where `local.prefix = "inbox-aggregator"`
- All resources tagged with `environment = var.environment`
- Lambda zips built via `data "archive_file"` from source directories
- Layer built via `null_resource` with `pip install --target .build/layer/python`
- Modules in `terraform/modules/`; each has `main.tf`, `variables.tf`, `outputs.tf`
- State bucket: `inbox-aggregator-tf-state` (S3, versioned, encrypted, private)

### Frontend
- React + Vite; source in `frontend/src/`
- Deployed to S3 (private) behind CloudFront

## Common Tasks

### Add a new Lambda
1. Create `lambdas/<name>/handler.py` with a `lambda_handler(event, context)` entry point
2. Add the Lambda resource in `terraform/modules/lambda/main.tf` following the existing pattern
3. Wire IAM policies, env vars, and event sources in `terraform/main.tf`
4. If the Lambda needs Gmail access, copy `gmail_client.py` into the new folder

### Add a dependency to the shared layer
1. Add the package to `lambdas/layer/requirements.txt`
2. The layer is rebuilt automatically on next `terraform apply` (keyed on `filemd5` of requirements.txt)

### Add a subscriber manually
```powershell
@'
{"PK": {"S": "SUBSCRIBER#+15551234567"}, "status": {"S": "ACTIVE"}, "name": {"S": "Name"}, "pushover_user_key": {"S": "key"}}
'@ | Out-File -Encoding ascii subscriber.json
aws dynamodb put-item --table-name inbox-aggregator-subscribers --region us-east-1 --item file://subscriber.json
Remove-Item subscriber.json
```

### Add a holding manually
```powershell
@'
{"PK": {"S": "PORTFOLIO#Main"}, "SK": {"S": "TICKER#AAPL"}, "ticker_pk": {"S": "TICKER#AAPL"}, "portfolio_sk": {"S": "PORTFOLIO#Main"}, "ticker": {"S": "AAPL"}, "portfolio_name": {"S": "Main"}, "shares": {"S": "50"}}
'@ | Out-File -Encoding ascii holding.json
aws dynamodb put-item --table-name inbox-aggregator-holdings --region us-east-1 --item file://holding.json
Remove-Item holding.json
```

### Run a Terraform plan locally
```bash
cd terraform
terraform init \
  -backend-config="bucket=inbox-aggregator-tf-state" \
  -backend-config="region=us-east-1"
terraform plan \
  -var="gcp_project_id=inbox-aggregator-493201" \
  -var="bedrock_model_id=anthropic.claude-haiku-4-5-20251001-v1:0"
```

## CI/CD

- **PR to `main`** → `pr-check.yml` runs `terraform plan` and posts output as a PR comment (requires OIDC AWS auth)
- **Merge to `main`** → deploy workflow runs `terraform apply`
- Lambda layer dependencies are installed in `.build/layer/python/` during the workflow before `terraform init`
- The S3 state bucket is created by the pipeline if it doesn't already exist

## What NOT to Do

- Do not hardcode AWS account IDs, credentials, or secrets in source files — use env vars or Secrets Manager references
- Do not add Lambda dependencies directly to a handler folder; add them to `lambdas/layer/requirements.txt`
- Do not modify the `import` block in `terraform/main.tf` that imports the pre-existing Gmail secret — it must remain to avoid Terraform trying to create a duplicate
- Do not change the Bedrock prompt in `email_processor/handler.py` without carefully testing extraction accuracy against real emails
