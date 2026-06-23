variable "domain_prefix" {
  description = "Globally-unique Cognito Hosted UI domain prefix."
  type        = string
}

variable "google_client_id" {
  description = "Google OAuth 2.0 client ID for the federated identity provider."
  type        = string
}

variable "google_client_secret" {
  description = "Google OAuth 2.0 client secret."
  type        = string
  sensitive   = true
}

variable "callback_urls" {
  description = "Allowed OAuth callback URLs (e.g. the CloudFront site URL)."
  type        = list(string)
}

variable "logout_urls" {
  description = "Allowed sign-out redirect URLs."
  type        = list(string)
}
