#!/usr/bin/env bash
# scripts/bootstrap.sh
#
# One-time setup: creates and hardens the S3 bucket used for Terraform state.
# Run this ONCE before the first `terraform init`.
#
# Prerequisites:
#   - AWS CLI installed and configured with appropriate credentials
#   - The target bucket name must be globally unique

set -euo pipefail

BUCKET="inbox-aggregator-tf-state"
REGION="us-east-1"

echo "==> Creating Terraform state bucket: $BUCKET in $REGION"

aws s3api create-bucket \
  --bucket "$BUCKET" \
  --region "$REGION"

echo "==> Enabling versioning..."
aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

echo "==> Blocking all public access..."
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "==> Enabling AES-256 server-side encryption..."
aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'

echo ""
echo "✓ Bucket '$BUCKET' is ready for Terraform state."
echo ""
echo "Next steps:"
echo "  1. Create the OIDC provider and GitHub Actions IAM role (see README.md)"
echo "  2. Set up GCP project and Pub/Sub (see README.md)"
echo "  3. Run: python scripts/setup_gmail_oauth.py --client-secret-file path/to/client_secret.json"
echo "  4. Enable Bedrock Claude Haiku model access in the AWS Console"
echo "  5. Add GitHub Secrets and Variables (see README.md)"
echo "  6. Push to main or open a PR to trigger the pipeline"
