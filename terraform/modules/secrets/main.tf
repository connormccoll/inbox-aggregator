# Gmail OAuth credentials (client_id, client_secret, refresh_token)
# Values are populated manually via scripts/setup_gmail_oauth.py
resource "aws_secretsmanager_secret" "gmail" {
  name                    = var.gmail_secrets_name
  description             = "Gmail OAuth2 credentials for inbox-aggregator. Populated by scripts/setup_gmail_oauth.py."
  recovery_window_in_days = 7

  tags = {
    Name = var.gmail_secrets_name
  }
}

