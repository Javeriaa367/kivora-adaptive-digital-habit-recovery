"""Rule-based in-app notification generator. Called on dashboard load
(no background scheduler needed for a project this size) -- checks a
user's activity and creates a notification if a rule fires AND one
with the same dedupe_key doesn't already exist (so it's not spammed
every page load)."""
from datetime import date

from database.db import create_notification_if_new, get_user_activity_summary


def generate_notifications_for_user(user_id: int):
    today = date.today().isoformat()
    activity = get_user_activity_summary(user_id)

    days_since_journal = activity["days_since_last_journal"]
    if days_since_journal is None or days_since_journal >= 2:
        create_notification_if_new(
            user_id,
            "You haven't journaled in a couple of days — a quick check-in helps keep your trends accurate.",
            "reminder", f"journal_reminder:{today}",
        )

    days_since_prediction = activity["days_since_last_prediction"]
    if days_since_prediction is None or days_since_prediction >= 7:
        create_notification_if_new(
            user_id,
            "It's been a week since your last assessment — run a new one to update your trends.",
            "reminder", f"prediction_reminder:{today}",
        )
