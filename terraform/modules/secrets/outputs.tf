output "gmail_secret_arn" {
  value = aws_secretsmanager_secret.gmail.arn
}

output "gmail_secret_name" {
  value = aws_secretsmanager_secret.gmail.name
}
