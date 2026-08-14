"""
AI Personal Wellness Coach: turns the raw 4-target prediction dict into a
natural-language explanation via Gemini, with a deterministic (non-LLM)
fallback so the feature still works without an API key.

Also: Daily Coach content (motivation / tip / reflection question),
deterministic per-day rotation, same pattern as gamification.get_daily_challenge
-- no LLM needed for this one, so it's free, instant, and identical for
everyone on a given day (fine for this use case; swap for LLM-generated
if you want per-user variety instead of a shared daily set).
"""
import hashlib
from datetime import date

from ml.chatbot import GEMINI_API_KEY, GEMINI_MODEL, get_gemini_client

REPORT_SYSTEM_PROMPT = (
    "You are a supportive, non-clinical wellness coach. You'll be given a "
    "user's model-predicted scores from a social-media-and-mental-wellbeing "
    "app. Write a short (150-220 word) personalized report with: one "
    "sentence acknowledging their overall picture, 1-2 genuine strengths, "
    "1-2 risk factors stated gently and without alarm, and 2-3 concrete, "
    "specific next steps. End with one encouraging sentence. Never use "
    "clinical/diagnostic language (no 'you have depression' etc.) -- these "
    "are statistical model outputs, not a diagnosis. Do not repeat the raw "
    "numbers back verbatim; interpret them in plain language."
)


def _fallback_report(predictions: dict) -> str:
    """Deterministic, rule-based report -- used when no Gemini key is set."""
    risk = predictions.get("addiction_risk_flag", {}).get("label")
    wb_score = predictions.get("wellbeing_score", {}).get("value")
    wb_flag = predictions.get("wellbeing_risk_flag", {}).get("label")

    lines = []
    if wb_flag == "Above median":
        lines.append(
            f"Your wellbeing score ({wb_score}/10) is above the typical range in this "
            "model — that's a solid foundation to build on."
        )
    else:
        lines.append(
            f"Your wellbeing score ({wb_score}/10) is on the lower side of the range this "
            "model has seen. That's worth paying attention to, not a cause for alarm."
        )

    if risk == "At-risk":
        lines.append(
            "Your usage pattern is currently flagged as at-risk. The behavioral flags carrying "
            "the most weight are usually late-night usage and how often you check first thing in "
            "the morning — small changes there tend to move the needle the most."
        )
    else:
        lines.append(
            "Your usage pattern isn't flagged as at-risk right now — worth maintaining."
        )

    lines.append(
        "A few concrete next steps: try a screen-free hour before bed, set an app timer on "
        "your most-used platform, and check in with your mood in the Journal a few times this "
        "week so trends become visible on your dashboard."
    )
    lines.append("Small, consistent changes compound — you don't need to fix everything at once.")
    return " ".join(lines)


def generate_wellness_report(predictions: dict) -> dict:
    if not GEMINI_API_KEY:
        return {"report": _fallback_report(predictions), "source": "rule_based"}

    prompt = (
        f"Addiction risk flag: {predictions.get('addiction_risk_flag', {}).get('label')} "
        f"(confidence {predictions.get('addiction_risk_flag', {}).get('confidence')})\n"
        f"Wellbeing score: {predictions.get('wellbeing_score', {}).get('value')}/10\n"
        f"Wellbeing risk flag: {predictions.get('wellbeing_risk_flag', {}).get('label')}"
    )
    try:
        client = get_gemini_client()
        resp = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt,
            config={"system_instruction": REPORT_SYSTEM_PROMPT, "max_output_tokens": 400},
        )
        text = (resp.text or "").strip()
        if not text:
            return {"report": _fallback_report(predictions), "source": "rule_based"}
        return {"report": text, "source": "gemini"}
    except Exception:
        return {"report": _fallback_report(predictions), "source": "rule_based"}


# ---- Daily Coach ---------------------------------------------------------
_MOTIVATIONS = [
    "Progress isn't linear — a rough day doesn't undo the good ones.",
    "You don't need a perfect routine, just a slightly better one than yesterday.",
    "Small consistent actions beat big occasional ones.",
    "Noticing a pattern is already half of changing it.",
    "Rest is productive too.",
]
_TIPS = [
    "Put your phone in another room for the first 30 minutes after waking up.",
    "Batch your notifications — check them at set times instead of as they arrive.",
    "Try eating one meal today with no screen in front of you.",
    "Text a friend instead of scrolling for 5 minutes.",
    "Step outside for 5 minutes, no phone.",
]
_REFLECTIONS = [
    "What's one thing that went better than expected today?",
    "When did you feel most present today?",
    "What's one small thing you're looking forward to tomorrow?",
    "Did anything today drain your energy more than it should have?",
    "What's one habit you're proud of maintaining this week?",
]


def _pick(options: list[str], salt: str, for_date: date) -> str:
    idx = int(hashlib.md5(f"{for_date.isoformat()}-{salt}".encode()).hexdigest(), 16) % len(options)
    return options[idx]


def get_daily_coach(for_date: date | None = None) -> dict:
    for_date = for_date or date.today()
    return {
        "motivation": _pick(_MOTIVATIONS, "motivation", for_date),
        "tip": _pick(_TIPS, "tip", for_date),
        "reflection_question": _pick(_REFLECTIONS, "reflection", for_date),
    }
