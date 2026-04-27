variable "gcp_project_id" {
  description = "GCP project ID."
  type        = string
}

variable "push_endpoint" {
  description = "HTTPS URL for the Pub/Sub push subscription (API Gateway /gmail-push endpoint)."
  type        = string
}
