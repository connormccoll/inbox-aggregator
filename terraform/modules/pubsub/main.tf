locals {
  topic_name = "inbox-aggregator-gmail-notifications"
}

# Pub/Sub topic that Gmail will publish change notifications to
resource "google_pubsub_topic" "gmail_notifications" {
  name    = local.topic_name
  project = var.gcp_project_id
}

# Grant Gmail's service account permission to publish to this topic
# This is required for gmail.users.watch() to work
resource "google_pubsub_topic_iam_member" "gmail_publish" {
  project = var.gcp_project_id
  topic   = google_pubsub_topic.gmail_notifications.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:gmail-api-push@system.gserviceaccount.com"
}

# Push subscription — Pub/Sub POSTs to API Gateway on each new notification
resource "google_pubsub_subscription" "gmail_push" {
  project = var.gcp_project_id
  name    = "inbox-aggregator-gmail-push-sub"
  topic   = google_pubsub_topic.gmail_notifications.name

  push_config {
    push_endpoint = var.push_endpoint
  }

  ack_deadline_seconds       = 20
  message_retention_duration = "600s" # 10 minutes — notifications are time-sensitive

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }
}
