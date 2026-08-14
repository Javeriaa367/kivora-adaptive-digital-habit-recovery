"""
Personalized recommendation engine. Pure function: (predictions, journal
mood, raw inputs) -> list of action cards. No side effects, no DB access --
easy to unit test and to call from both /api/predict and /api/journal.
"""

CARD_LIBRARY = {
    "stress": {
        "icon": "fa-wind", "color": "amber", "title": "Manage stress",
        "actions": [
            "Try box breathing: 4 counts in, 4 hold, 4 out, 4 hold.",
            "A 10-minute guided meditation can reset a tense afternoon.",
            "Take a real break — step away from the screen entirely.",
            "Progressive muscle relaxation before bed can lower tension.",
        ],
    },
    "depression_support": {
        "icon": "fa-heart", "color": "coral", "title": "Support your mood",
        "actions": [
            "Reach out to one person you trust today, even briefly.",
            "Light activity — a short walk counts — reliably lifts mood.",
            "If this feeling persists, consider talking to a professional.",
        ],
    },
    "sleep": {
        "icon": "fa-moon", "color": "teal", "title": "Protect your sleep",
        "actions": [
            "Keep a consistent bedtime, even on weekends.",
            "Cut screens ~30 minutes before bed — the scrolling delays sleep more than the light does.",
        ],
    },
    "digital_detox": {
        "icon": "fa-mobile-screen", "color": "amber", "title": "Rebalance screen time",
        "actions": [
            "Set an app timer on your most-used platform.",
            "Try a defined \"detox window\" each day — no phone for 1-2 hours.",
            "Move social apps off your home screen to add friction.",
        ],
    },
    "productivity": {
        "icon": "fa-list-check", "color": "slate", "title": "Rebuild focus",
        "actions": [
            "Try the Pomodoro method: 25 minutes focused, 5 minute break.",
            "Write down your top 3 priorities before opening any app.",
        ],
    },
}


def get_recommendations(predictions: dict | None, journal_emotion: str | None = None,
                         crisis: bool = False) -> list[dict]:
    """predictions: the dict returned by ml.predictor.predict_all (or None).
    journal_emotion: latest journal EMOTIONS label, if any.
    crisis: True skips normal recommendations -- the crisis banner covers it.
    """
    if crisis:
        return []

    cards = []
    seen = set()

    def add(key):
        if key not in seen:
            seen.add(key)
            cards.append(CARD_LIBRARY[key])

    predictions = predictions or {}

    addiction_risk = predictions.get("addiction_risk_flag", {}).get("label")
    wellbeing_flag = predictions.get("wellbeing_risk_flag", {}).get("label")
    wellbeing_score = predictions.get("wellbeing_score", {}).get("value")

    if addiction_risk == "At-risk":
        add("digital_detox")
        add("stress")

    if wellbeing_flag == "Below median" or (wellbeing_score is not None and wellbeing_score < 4.0):
        add("depression_support")

    if journal_emotion in ("Stressed", "Anxious"):
        add("stress")

    if journal_emotion == "Sad":
        add("depression_support")

    if journal_emotion == "Angry":
        add("stress")

    # Always offer at least one card so the panel is never empty after a
    # real prediction/journal entry -- sleep hygiene is broadly useful.
    if not cards:
        add("sleep")

    return cards
