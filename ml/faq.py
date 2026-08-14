"""AI FAQ bot: matches against a curated Q&A base first (fast, free,
accurate for known questions), falls back to Gemini for anything else
(if configured), and finally to an honest "I don't know" rather than
guessing."""
import re

from ml.chatbot import GEMINI_API_KEY, GEMINI_MODEL, get_gemini_client

FAQ_ENTRIES = [
    (r"\b(what|how).*(addiction risk|addiction level)\b",
     "Addiction risk is a binary flag (at-risk / not) from a model trained on usage patterns like "
     "late-night use and daily hours — about 83% accurate on test data. We show that single, more "
     "reliable signal to you directly; the finer 4-category level breakdown exists internally but is "
     "too imprecise (~59%) to headline."),
    (r"\b(wellbeing score|mental wellbeing)\b",
     "Wellbeing score is a 0-10 continuous prediction from your usage inputs (R² ≈ 0.66 — moderately "
     "accurate, not exact). The wellbeing risk flag is a simpler above/below-median version that's "
     "more reliable (~78% accurate)."),
    (r"\b(free plan|premium|subscription|upgrade|pricing)\b",
     "Free plan includes 3 assessments/day plus full journal, habits, and mind games. Premium removes "
     "the daily cap and unlocks AI-generated wellness reports. See the Pricing page to upgrade."),
    (r"\b(journal|emotion|mood detect)\b",
     "The journal analyzes what you write and detects one of 7 moods (Happy, Calm, Neutral, Stressed, "
     "Anxious, Sad, Angry) plus an overall sentiment. It's a supportive tool for spotting patterns over "
     "time, not a clinical diagnosis."),
    (r"\b(delete|privacy|data)\b",
     "Your journal entries, assessments, and habit data are stored in the app's database tied to your "
     "account. From Settings you can download a full copy of your data, or delete your account and "
     "everything it contains. Our Privacy Policy explains exactly what we store and why."),
    (r"\b(crisis|emergency|suicide|self.?harm)\b",
     "If you're in crisis, please don't wait on this FAQ bot — the app shows crisis "
     "resources for your region (your country's helplines, or international "
     "directories if we don't have them) whenever it detects concerning language in "
     "your journal or chat. In an emergency, call your local emergency number."),
]

_FALLBACK_NO_MODEL = (
    "I don't have an answer for that one — try the Feedback page to ask a "
    "human, or check the FAQ for related topics."
)

FAQ_SYSTEM_PROMPT = (
    "You are a concise FAQ assistant for Kivora, a social-media-wellbeing app with ML "
    "predictions, a mood journal, habits, and a coaching chatbot. Answer only questions about how "
    "the app works, in 1-3 sentences. If asked something outside that scope, say so briefly. Never "
    "give clinical or diagnostic advice."
)


def answer_faq(question: str) -> dict:
    lower = question.lower()
    for pattern, answer in FAQ_ENTRIES:
        if re.search(pattern, lower):
            return {"answer": answer, "source": "faq_base"}

    if not GEMINI_API_KEY:
        return {"answer": _FALLBACK_NO_MODEL, "source": "fallback"}

    try:
        client = get_gemini_client()
        resp = client.models.generate_content(
            model=GEMINI_MODEL, contents=question,
            config={"system_instruction": FAQ_SYSTEM_PROMPT, "max_output_tokens": 200},
        )
        text = (resp.text or "").strip()
        return {"answer": text or _FALLBACK_NO_MODEL, "source": "gemini" if text else "fallback"}
    except Exception:
        return {"answer": _FALLBACK_NO_MODEL, "source": "fallback"}
