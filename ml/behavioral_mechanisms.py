"""
Behavioral Mechanism Inference (Adaptive Recovery Engine, Phase 3/4).

Answers a narrower question than ml/risk_engine.py's "how elevated is this
risk category" -- it asks WHY the usage is happening, from real stored
signals only:

    - assessment inputs already collected by ml/predictor.py (FOMO_Score,
      Social_Comparison_Score, Scroll_Without_Purpose, First_Check_Morning,
      Notifications_Per_Day, Late_Night_Usage, Daily_Usage_Hours)
    - journal emotion labels around usage (ml/emotion_analyzer.py)
    - long-term memory triggers/stressors (ml/memory.py)

This is deliberately NOT a diagnosis and NOT a trained classifier -- same
reasoning as risk_engine.py's own docstring. Every mechanism returned ships
with the literal reasons that produced it. If there isn't enough evidence
to name one with any confidence, the function says so instead of guessing
-- ml/recovery_plans.py must never fabricate personalization on top of an
unknown mechanism.

MECHANISMS intentionally mirrors the list requested for KIVORA's recovery
engine: automatic_checking, boredom, emotional_avoidance, fomo,
sleep_disruption, procrastination, social_comparison, stress_triggered,
loneliness_driven, notification_triggered, cant_stop_once_started.
"""
from database.db import get_recent_predictions
from ml.memory import get_memory_context

MECHANISMS = [
    "automatic_checking", "boredom", "emotional_avoidance", "fomo",
    "sleep_disruption", "procrastination", "social_comparison",
    "stress_triggered", "loneliness_driven", "notification_triggered",
    "cant_stop_once_started",
]

_STRESS_TRIGGER_WORDS = ("stress", "overwhelm", "deadline", "pressure", "work", "exam")
_PROCRASTINATION_WORDS = ("procrastinat", "study", "avoid work", "putting off", "assignment")
_AVOIDANCE_WORDS = ("avoid", "escape", "distract", "numb", "cope")


def _latest_inputs(predictions: list[dict]) -> dict:
    return predictions[-1]["inputs"] if predictions else {}


def _num(inputs: dict, field: str):
    val = inputs.get(field)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _truthy(inputs: dict, field: str) -> bool:
    return str(inputs.get(field)) in ("1", "1.0", "True", "true")


def score_mechanisms(user_id: int) -> dict:
    """Returns {mechanism: {"score": int, "reasons": [str, ...]}} for every
    mechanism with at least one real signal behind it. A mechanism absent
    from the dict simply had zero supporting evidence -- not a zero score
    asserted, an absence of a claim."""
    predictions = get_recent_predictions(user_id, limit=5)[::-1]
    inputs = _latest_inputs(predictions)
    memory = get_memory_context(user_id)
    triggers = memory["facts_by_type"].get("trigger", [])
    stressors = memory["facts_by_type"].get("stressor", [])
    trigger_texts = [t["text"].lower() for t in triggers]
    stressor_texts = [s["text"].lower() for s in stressors]

    out: dict = {}

    def add(mechanism: str, points: int, reason: str):
        entry = out.setdefault(mechanism, {"score": 0, "reasons": []})
        entry["score"] += points
        entry["reasons"].append(reason)

    if not inputs:
        return out  # no assessment on file yet -- nothing to infer from

    first_check = _num(inputs, "First_Check_Morning")
    if first_check == 1:
        add("automatic_checking", 3, "your last assessment reported checking social media first thing in the morning")

    notifications = _num(inputs, "Notifications_Per_Day")
    if notifications is not None and notifications >= 40:
        add("notification_triggered", 3, f"your last assessment reported {int(notifications)} notifications/day")
        add("automatic_checking", 1, f"{int(notifications)} notifications/day makes checking easy to trigger automatically")

    scroll = _num(inputs, "Scroll_Without_Purpose")
    if scroll is not None and scroll >= 7:
        add("cant_stop_once_started", 3, f"your last assessment scored scrolling-without-purpose at {int(scroll)}/10")
        add("boredom", 1, "high purposeless scrolling often shows up alongside boredom-driven usage")

    fomo = _num(inputs, "FOMO_Score")
    if fomo is not None and fomo >= 7:
        add("fomo", 3, f"your last assessment scored FOMO at {int(fomo)}/10")

    comparison = _num(inputs, "Social_Comparison_Score")
    if comparison is not None and comparison >= 7:
        add("social_comparison", 3, f"your last assessment scored social comparison at {int(comparison)}/10")

    if _truthy(inputs, "Late_Night_Usage"):
        add("sleep_disruption", 3, "your last assessment reported late-night usage")

    usage_series = [v for v in (_num(_latest_inputs([p]), "Daily_Usage_Hours") for p in predictions) if v is not None]
    screen_free = _num(inputs, "Screen_Free_Time_Hrs")
    if screen_free is not None and screen_free <= 1.0 and usage_series and usage_series[-1] >= 4:
        add("boredom", 2, f"screen-free time is only {screen_free:.1f}h/day alongside {usage_series[-1]:.1f}h of daily usage")

    if any(any(w in t for w in _STRESS_TRIGGER_WORDS) for t in trigger_texts + stressor_texts):
        matched = next(t for t in trigger_texts + stressor_texts if any(w in t for w in _STRESS_TRIGGER_WORDS))
        add("stress_triggered", 2, f'a stress-related trigger/stressor is active in your memory: "{matched}"')

    if any(any(w in t for w in _PROCRASTINATION_WORDS) for t in trigger_texts + stressor_texts):
        matched = next(t for t in trigger_texts + stressor_texts if any(w in t for w in _PROCRASTINATION_WORDS))
        add("procrastination", 2, f'a study/work-avoidance trigger is active in your memory: "{matched}"')

    if any(any(w in t for w in _AVOIDANCE_WORDS) for t in trigger_texts):
        matched = next(t for t in trigger_texts if any(w in t for w in _AVOIDANCE_WORDS))
        add("emotional_avoidance", 2, f'an avoidance-related trigger is active in your memory: "{matched}"')

    relational = [t for t in trigger_texts if any(w in t for w in ("lonely", "friend", "relationship", "alone"))]
    quality = _num(inputs, "Offline_Relationship_Quality")
    if relational:
        add("loneliness_driven", 2, f'a relationship-related trigger is active in your memory: "{relational[0]}"')
    if quality is not None and quality <= 3:
        add("loneliness_driven", 1, f"your most recent offline relationship quality score was {quality:.0f}/10")

    return out


def infer_mechanism(user_id: int) -> tuple[str | None, list[str], bool]:
    """Returns (mechanism, reasons, has_evidence). mechanism is None when
    no signal cleared a minimum bar -- callers must treat that as "unknown"
    and fall back to the risk-category-level plan, never invent a
    mechanism to look more personalized than the data supports."""
    from database.db import get_recent_predictions

    has_evidence = bool(get_recent_predictions(user_id, limit=1))
    scored = score_mechanisms(user_id)
    if not scored:
        return None, [], has_evidence
    top_mechanism, top = max(scored.items(), key=lambda kv: kv[1]["score"])
    if top["score"] < 3:
        return None, [], has_evidence
    return top_mechanism, top["reasons"], has_evidence
