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

# Placeholder — actual value injected by setup_gmail_oauth.py
resource "aws_secretsmanager_secret_version" "gmail_placeholder" {
  secret_id = aws_secretsmanager_secret.gmail.id
  secret_string = jsonencode({
    client_id     = "PLACEHOLDER"
    client_secret = "PLACEHOLDER"
    refresh_token = "PLACEHOLDER"
  })

  lifecycle {
    # Prevent Terraform from overwriting values injected by the setup script
    ignore_changes = [secret_string]
  }
}
