"""
Early Risk Detection (Feature 2).

A transparent, auditable point-scoring engine across five categories --
depression, burnout, anxiety, digital_addiction, loneliness -- built from
signals that actually exist in this app:

    - journal sentiment/emotion trend (journal_entries)
    - prediction history: wellbeing_score, addiction_risk_flag, and the raw
      assessment inputs (Sleep_Hours, Daily_Usage_Hours, FOMO_Score, etc.)
    - habit check-in consistency, as a productivity/engagement proxy
    - long-term memory facts (ml/memory.py) -- recurring stressors/triggers

This is deliberately NOT a trained classifier: there is no historical
"user X later developed burnout" label data anywhere in this app to train
one honestly on (same reasoning as ml/churn.py's existing heuristic).
Calling a heuristic a "prediction" would overclaim what it is, so every
level here ships with the literal reasons that produced it -- nothing is
asserted that isn't traceable back to a stored number.

Levels: low / moderate / high / critical, from a 0-10+ point score per
category. Any single "critical" reason (e.g. a crisis-flagged journal
entry) can push a category straight to "critical" regardless of total
score -- severity signals aren't just additive.
"""
from datetime import datetime, timedelta, timezone

from database.db import (
    get_habit_checkins_by_week,
    get_journal_entries_since,
    get_recent_predictions,
    insert_risk_snapshot,
)
from ml.chatbot import GEMINI_API_KEY, GEMINI_MODEL, get_gemini_client
from ml.memory import get_memory_context

CATEGORIES = ["depression", "burnout", "anxiety", "digital_addiction", "loneliness"]
LEVEL_THRESHOLDS = [(8, "critical"), (5, "high"), (2, "moderate"), (0, "low")]

EXPLAIN_SYSTEM_PROMPT = (
    "You rewrite a risk-engine's factual reason list into ONE warm, plain-"
    "language sentence for a mental wellness app. Use ONLY the reasons given "
    "-- do not add, infer, or soften away any of them, and do not invent "
    "numbers. Never use diagnostic language ('you have X'); frame it as a "
    "pattern the data shows, not a diagnosis. Keep it under 40 words."
)


def _level_for_score(score: int) -> str:
    for threshold, level in LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return "low"


def _weekly_journal_sentiment(user_id: int, weeks: int = 6):
    since = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()
    entries = get_journal_entries_since(user_id, since)
    by_week: dict = {}
    for e in entries:
        wk = datetime.fromisoformat(e["created_at"]).isocalendar()[:2]
        by_week.setdefault(wk, []).append(e)
    weeks_sorted = sorted(by_week.keys())
    return [
        {
            "avg_sentiment": sum(e["sentiment_score"] for e in by_week[wk]) / len(by_week[wk]),
            "emotions": [e["emotion_label"] for e in by_week[wk]],
            "any_crisis": any(e["crisis_flag"] for e in by_week[wk]),
        }
        for wk in weeks_sorted
    ], entries


def _is_declining(series: list[float], min_len: int = 3) -> bool:
    """True if the last `min_len` points are non-increasing and strictly
    lower at the end than the start -- a real multi-period decline, not
    single-point noise."""
    if len(series) < min_len:
        return False
    tail = series[-min_len:]
    return all(tail[i] >= tail[i + 1] for i in range(len(tail) - 1)) and tail[0] > tail[-1]


def _prediction_input_series(predictions: list[dict], field: str) -> list[float]:
    out = []
    for p in predictions:
        val = p["inputs"].get(field)
        if val is not None:
            try:
                out.append(float(val))
            except (TypeError, ValueError):
                pass
    return out


def _score_depression(weekly, entries, predictions, memory):
    score, reasons, critical = 0, [], False
    sentiments = [w["avg_sentiment"] for w in weekly]
    if any(w["any_crisis"] for w in weekly[-2:]):
        score += 10; critical = True
        reasons.append("a recent journal entry was flagged for crisis language")
    if _is_declining(sentiments):
        score += 3
        reasons.append(f"journal sentiment has declined for {len(sentiments[-3:])} consecutive weeks "
                        f"({sentiments[-3]:.2f} → {sentiments[-1]:.2f})")
    sad_count = sum(1 for e in entries if e["emotion_label"] == "Sad")
    if entries and sad_count / len(entries) >= 0.4:
        score += 2
        reasons.append(f"{sad_count} of your last {len(entries)} journal entries were logged as Sad")
    wb_scores = [p["results"].get("wellbeing_score", {}).get("value") for p in predictions]
    wb_scores = [v for v in wb_scores if v is not None]
    if _is_declining(wb_scores):
        score += 2
        reasons.append(f"your predicted wellbeing score has declined over your last {len(wb_scores)} assessments")
    stressors = len(memory["facts_by_type"].get("stressor", []))
    if stressors >= 3:
        score += 1
        reasons.append(f"{stressors} recurring stressors are active in your memory")
    return score, reasons, critical


def _score_burnout(weekly, entries, predictions, memory, checkins_by_week):
    score, reasons, critical = 0, [], False
    if _is_declining(checkins_by_week):
        score += 3
        reasons.append(f"habit check-ins have dropped for {len(checkins_by_week[-3:])} consecutive weeks "
                        f"({checkins_by_week[-3]} → {checkins_by_week[-1]} per week)")
    neg_emotions = {"Stressed", "Anxious", "Sad", "Angry"}
    if len(weekly) >= 3:
        neg_ratio = [
            sum(1 for em in w["emotions"] if em in neg_emotions) / max(1, len(w["emotions"]))
            for w in weekly[-3:]
        ]
        if neg_ratio[0] < neg_ratio[-1] and neg_ratio[-1] >= 0.5:
            score += 2
            reasons.append("negative-sentiment journal entries have been increasing over the last 3 weeks")
    sleep_series = _prediction_input_series(predictions, "Sleep_Hours")
    if _is_declining(sleep_series):
        score += 2
        reasons.append(f"reported sleep hours have been declining ({sleep_series[-3]:.1f}h → {sleep_series[-1]:.1f}h)")
    stressors = len(memory["facts_by_type"].get("stressor", []))
    if stressors >= 2:
        score += 1
        reasons.append(f"{stressors} recurring stressors are active in your memory")
    return score, reasons, critical


def _score_anxiety(weekly, entries, predictions, memory):
    score, reasons, critical = 0, [], False
    anx_count = sum(1 for e in entries if e["emotion_label"] == "Anxious")
    if entries and anx_count / len(entries) >= 0.35:
        score += 3
        reasons.append(f"{anx_count} of your last {len(entries)} journal entries were logged as Anxious")
    fomo_series = _prediction_input_series(predictions, "FOMO_Score")
    comparison_series = _prediction_input_series(predictions, "Social_Comparison_Score")
    if fomo_series and fomo_series[-1] >= 7:
        score += 2
        reasons.append(f"your most recent FOMO score was {fomo_series[-1]:.0f}/10")
    if comparison_series and comparison_series[-1] >= 7:
        score += 2
        reasons.append(f"your most recent social comparison score was {comparison_series[-1]:.0f}/10")
    sleep_facts = memory["facts_by_type"].get("sleep_pattern", [])
    trigger_facts = memory["facts_by_type"].get("trigger", [])
    if sleep_facts and trigger_facts:
        score += 1
        reasons.append("both a sleep pattern and an emotional trigger are active in your memory")
    return score, reasons, critical


def _score_digital_addiction(predictions, memory):
    score, reasons, critical = 0, [], False
    if predictions:
        latest = predictions[-1]["results"]
        flag = latest.get("addiction_risk_flag", {}).get("label")
        if flag == "At-risk":
            score += 3
            reasons.append("your most recent assessment flagged addiction risk as 'At-risk'")
    usage_series = _prediction_input_series(predictions, "Daily_Usage_Hours")
    if len(usage_series) >= 2 and usage_series[-1] > usage_series[0]:
        score += 2
        reasons.append(f"daily usage hours have risen ({usage_series[0]:.1f}h → {usage_series[-1]:.1f}h)")
    if predictions:
        latest_inputs = predictions[-1]["inputs"]
        if str(latest_inputs.get("Late_Night_Usage")) in ("1", "1.0", "True", "true"):
            score += 2
            reasons.append("your most recent assessment reported late-night usage")
        if str(latest_inputs.get("Failed_To_Cut_Back")) in ("1", "1.0", "True", "true"):
            score += 2
            reasons.append("your most recent assessment reported a failed attempt to cut back")
    return score, reasons, critical


def _score_loneliness(entries, predictions, memory):
    score, reasons, critical = 0, [], False
    quality_series = _prediction_input_series(predictions, "Offline_Relationship_Quality")
    if _is_declining(quality_series):
        score += 3
        reasons.append(f"offline relationship quality has declined over your last {len(quality_series)} assessments")
    elif quality_series and quality_series[-1] <= 3:
        score += 2
        reasons.append(f"your most recent offline relationship quality score was {quality_series[-1]:.0f}/10")
    triggers = memory["facts_by_type"].get("trigger", [])
    relational = [t for t in triggers if "relationship" in t["text"].lower() or "friend" in t["text"].lower()
                  or "family" in t["text"].lower() or "parent" in t["text"].lower()]
    if relational:
        score += 2
        reasons.append(f"a relationship-related trigger is active in your memory: \"{relational[0]['text']}\"")
    sad_count = sum(1 for e in entries if e["emotion_label"] == "Sad")
    if entries and sad_count / len(entries) >= 0.3:
        score += 1
        reasons.append(f"{sad_count} of your last {len(entries)} journal entries were logged as Sad")
    return score, reasons, critical


def compute_risk_profile(user_id: int, persist: bool = True) -> dict:
    """Computes all 5 category risk levels from real stored signals.
    persist=True writes one risk_snapshots row per category (used for the
    trend chart) -- callers that just want a read (e.g. a dashboard widget
    refreshing on every page load) should pass persist=False."""
    weekly, entries = _weekly_journal_sentiment(user_id)
    predictions = get_recent_predictions(user_id, limit=10)[::-1]  # oldest first
    memory = get_memory_context(user_id)
    checkins_by_week = get_habit_checkins_by_week(user_id)
    # Distinguishes "we looked and found nothing elevated" from "we have
    # nothing to look at yet" -- a brand-new account with zero journal
    # entries, predictions, and check-ins previously got the exact same
    # "No elevated risk signals right now" wording as someone with months
    # of consistently calm history, which reads as false reassurance.
    has_evidence = bool(entries) or bool(predictions) or any(checkins_by_week)

    scorers = {
        "depression": lambda: _score_depression(weekly, entries, predictions, memory),
        "burnout": lambda: _score_burnout(weekly, entries, predictions, memory, checkins_by_week),
        "anxiety": lambda: _score_anxiety(weekly, entries, predictions, memory),
        "digital_addiction": lambda: _score_digital_addiction(predictions, memory),
        "loneliness": lambda: _score_loneliness(entries, predictions, memory),
    }

    profile = {}
    for category, fn in scorers.items():
        score, reasons, forced_critical = fn()
        level = "critical" if forced_critical else _level_for_score(score)
        explanation = generate_risk_explanation(category, level, reasons, has_evidence)
        profile[category] = {
            "score": score, "level": level, "reasons": reasons, "explanation": explanation,
        }
        if persist:
            import json
            insert_risk_snapshot(user_id, category, level, score, json.dumps(reasons))

    return profile


def generate_risk_explanation(category: str, level: str, reasons: list[str],
                               has_evidence: bool = True) -> str:
    """Grounded-only explanation: given the deterministic reasons list, this
    either returns them joined plainly, or asks Gemini to smooth them into
    one sentence -- constrained to those exact reasons, nothing else.

    has_evidence distinguishes "checked and nothing elevated" from "nothing
    to check yet" -- see the comment in compute_risk_profile(). Defaults to
    True so any other/older caller keeps today's exact wording."""
    if not reasons:
        if not has_evidence:
            return (
                f"Not enough journal entries or check-ins yet to look for "
                f"{category.replace('_', ' ')} patterns — this will start "
                f"reflecting real signal as you keep logging."
            )
        return f"No elevated {category.replace('_', ' ')} risk signals right now."

    fallback = f"Your {category.replace('_', ' ')} risk is {level} because " + "; ".join(reasons) + "."

    if GEMINI_API_KEY:
        try:
            client = get_gemini_client()
            prompt = (
                f"{EXPLAIN_SYSTEM_PROMPT}\n\nCategory: {category}\nLevel: {level}\n"
                f"Reasons:\n" + "\n".join(f"- {r}" for r in reasons)
            )
            response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            text = (response.text or "").strip()
            if text:
                return text
        except Exception:
            pass

    return fallback


def get_risk_trend(user_id: int, days: int = 90) -> dict:
    from database.db import get_risk_history
    out = {}
    for category in CATEGORIES:
        rows = get_risk_history(user_id, category, days)
        out[category] = [{"date": r["created_at"][:10], "score": r["score"], "level": r["level"]} for r in rows]
    return out
