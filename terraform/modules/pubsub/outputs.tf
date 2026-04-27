output "topic_name" {
  value = google_pubsub_topic.gmail_notifications.name
}

output "topic_id" {
  value = google_pubsub_topic.gmail_notifications.id
}

output "subscription_name" {
  value = google_pubsub_subscription.gmail_push.name
}
