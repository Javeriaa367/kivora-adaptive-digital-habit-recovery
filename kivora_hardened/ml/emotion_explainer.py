"""Brief explanation of why a given emotion was detected -- Gemini-backed
with a template-based fallback so the journal feature never breaks
without an API key."""
from ml.chatbot import GEMINI_API_KEY, GEMINI_MODEL, get_gemini_client

EXPLAIN_SYSTEM_PROMPT = (
    "You explain, in ONE short sentence (under 25 words), why a journal entry was "
    "classified with a given mood label. Be specific to what the person wrote, warm "
    "in tone, and never clinical or diagnostic. Emotion and sentiment are independent: "
    "never say a mood was detected because the overall tone is positive, negative, or neutral."
)


def _fallback_explanation(text: str, analysis: dict) -> str:
    label = analysis["emotion_label"]
    sentiment = analysis["overall_sentiment"]
    secondary = analysis.get("secondary_emotion")
    low_confidence = analysis.get("low_confidence")

    if low_confidence:
        return (
            f"The sentiment reads as {sentiment}, with a {label.lower()} mood signal -- though it's a short "
            "entry, so take that read as a rough signal rather than a firm one."
        )

    base = (
        f"The detected mood is {label}, while the overall sentiment reads as {sentiment}, "
        "based on the words and phrasing used."
    )
    if secondary:
        base += f" There's also a hint of {secondary.lower()} in there, which is worth noticing too."
    return base


def generate_emotion_explanation(text: str, analysis: dict) -> str:
    if not GEMINI_API_KEY:
        return _fallback_explanation(text, analysis)

    secondary = analysis.get("secondary_emotion")
    mood_line = f"Detected mood: {analysis['emotion_label']}"
    if secondary:
        mood_line += f" (with some {secondary} also present)"
    if analysis.get("low_confidence"):
        mood_line += "\nNote: this is a short/ambiguous entry, so the signal is weak -- acknowledge that lightly if natural."
    sentiment_line = f"Overall sentiment: {analysis['overall_sentiment']}"
    prompt = (
        f"Journal entry: \"{text}\"\n{mood_line}\n{sentiment_line}\n"
        "Explain the mood without claiming that the mood label and sentiment must match."
    )
    try:
        client = get_gemini_client()
        resp = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt,
            config={"system_instruction": EXPLAIN_SYSTEM_PROMPT, "max_output_tokens": 80},
        )
        text_out = (resp.text or "").strip()
        return text_out or _fallback_explanation(text, analysis)
    except Exception:
        return _fallback_explanation(text, analysis)
