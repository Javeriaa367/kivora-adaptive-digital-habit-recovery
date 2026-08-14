"""Gamification: badges (computed from real usage counts) and a daily
challenge (deterministic rotation, no state needed)."""
import hashlib
from datetime import date

BADGES = [
    {"id": "first_entry", "name": "First Step", "icon": "fa-seedling", "desc": "Wrote your first journal entry",
     "check": lambda s: s["total_journal_entries"] >= 1},
    {"id": "streak_3", "name": "3-Day Streak", "icon": "fa-fire", "desc": "Journaled 3 days in a row",
     "check": lambda s: s["journal_streak_days"] >= 3},
    {"id": "streak_7", "name": "Week Warrior", "icon": "fa-fire-flame-curved", "desc": "Journaled 7 days in a row",
     "check": lambda s: s["journal_streak_days"] >= 7},
    {"id": "streak_30", "name": "Habit Formed", "icon": "fa-trophy", "desc": "Journaled 30 days in a row",
     "check": lambda s: s["journal_streak_days"] >= 30},
    {"id": "entries_10", "name": "Reflective Mind", "icon": "fa-book-open", "desc": "10 journal entries logged",
     "check": lambda s: s["total_journal_entries"] >= 10},
    {"id": "first_prediction", "name": "Data-Driven", "icon": "fa-chart-line", "desc": "Ran your first assessment",
     "check": lambda s: s["total_predictions"] >= 1},
    {"id": "predictions_5", "name": "Consistent Checker", "icon": "fa-magnifying-glass-chart", "desc": "5 assessments run",
     "check": lambda s: s["total_predictions"] >= 5},
]

_CHALLENGES = [
    "Write a journal entry before checking any social app today.",
    "Take a 10-minute walk without your phone.",
    "Try 4-4-4-4 box breathing for 2 minutes.",
    "Message a friend instead of scrolling for 10 minutes.",
    "Set a notification-free hour this evening.",
    "Write down one thing that went well today.",
    "Do a 5-minute stretch break away from screens.",
]


def compute_badges(stats: dict) -> list[dict]:
    earned = []
    for b in BADGES:
        if b["check"](stats):
            earned.append({"id": b["id"], "name": b["name"], "icon": b["icon"], "desc": b["desc"]})
    return earned


def get_daily_challenge(for_date: date | None = None) -> str:
    for_date = for_date or date.today()
    idx = int(hashlib.md5(for_date.isoformat().encode()).hexdigest(), 16) % len(_CHALLENGES)
    return _CHALLENGES[idx]
