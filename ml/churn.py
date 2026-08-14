"""
Churn RISK heuristic -- NOT a trained ML model. There's no historical
churn-label data in this app (no users have actually churned yet to
learn from), so a real classifier can't be trained honestly. This is a
transparent, auditable point-scoring rule instead. Swap for a real
model once you have enough churned-vs-retained user history to train
one -- until then, calling this a "prediction" would overclaim what
it actually is.
"""
from database.db import get_user_activity_summary


def compute_churn_risk(user_id: int) -> dict:
    activity = get_user_activity_summary(user_id)
    days_journal = activity["days_since_last_journal"]
    days_prediction = activity["days_since_last_prediction"]

    score = 0
    reasons = []

    if days_journal is None:
        score += 2; reasons.append("never journaled")
    elif days_journal >= 14:
        score += 3; reasons.append(f"no journal entry in {days_journal}d")
    elif days_journal >= 7:
        score += 1; reasons.append(f"no journal entry in {days_journal}d")

    if days_prediction is None:
        score += 2; reasons.append("never ran an assessment")
    elif days_prediction >= 21:
        score += 3; reasons.append(f"no assessment in {days_prediction}d")
    elif days_prediction >= 10:
        score += 1; reasons.append(f"no assessment in {days_prediction}d")

    level = "high" if score >= 5 else "medium" if score >= 2 else "low"
    return {"score": score, "level": level, "reasons": reasons}
