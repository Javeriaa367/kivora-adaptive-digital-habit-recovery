"""AI Study Coach: generates a study schedule from subjects + exam dates
+ daily available hours. Gemini-backed with a deterministic rule-based
fallback (round-robin by urgency) so it works without an API key."""
from datetime import date, datetime

from ml.chatbot import GEMINI_API_KEY, GEMINI_MODEL, get_gemini_client

STUDY_SYSTEM_PROMPT = (
    "You are a study planning assistant. Given a list of subjects with exam dates and a student's "
    "daily available study hours, produce a short, practical weekly study plan. Prioritize subjects "
    "with closer exam dates. Keep it to plain text, one line per subject with suggested hours/week "
    "and a one-sentence tip. Do not use markdown headers."
)


def _days_until(exam_date: str | None) -> int | None:
    if not exam_date:
        return None
    try:
        d = datetime.fromisoformat(exam_date).date()
        return (d - date.today()).days
    except ValueError:
        return None


def _fallback_plan(subjects: list[dict], daily_hours: float) -> str:
    weekly_hours = daily_hours * 7
    with_urgency = []
    for s in subjects:
        days = _days_until(s.get("exam_date"))
        urgency = 1 / max(days, 1) if days is not None else 0.1
        with_urgency.append((s, urgency))

    total_urgency = sum(u for _, u in with_urgency) or 1
    lines = []
    for s, urgency in sorted(with_urgency, key=lambda x: -x[1]):
        share = urgency / total_urgency
        hours = round(weekly_hours * share, 1)
        days = _days_until(s.get("exam_date"))
        due_note = f"{days} days until exam" if days is not None else "no exam date set"
        lines.append(f"{s['name']}: ~{hours}h this week ({due_note})")
    return "\n".join(lines) if lines else "Add a subject to get a study plan."


def generate_study_plan(subjects: list[dict], daily_hours: float) -> dict:
    if not subjects:
        return {"plan": "Add a subject with an exam date to get a personalized study plan.", "source": "none"}

    if not GEMINI_API_KEY:
        return {"plan": _fallback_plan(subjects, daily_hours), "source": "rule_based"}

    subject_lines = "\n".join(
        f"- {s['name']}: exam {s.get('exam_date') or 'not set'}" for s in subjects
    )
    prompt = f"Daily available study hours: {daily_hours}\nSubjects:\n{subject_lines}"
    try:
        client = get_gemini_client()
        resp = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt,
            config={"system_instruction": STUDY_SYSTEM_PROMPT, "max_output_tokens": 350},
        )
        text = (resp.text or "").strip()
        return {"plan": text or _fallback_plan(subjects, daily_hours), "source": "gemini" if text else "rule_based"}
    except Exception:
        return {"plan": _fallback_plan(subjects, daily_hours), "source": "rule_based"}
