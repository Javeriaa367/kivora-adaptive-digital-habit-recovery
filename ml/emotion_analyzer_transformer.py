"""
Transformer-based emotion analyzer -- drop-in replacement for
LexiconEmotionAnalyzer. Implements the same EmotionAnalyzer interface
from ml/emotion_analyzer.py, so nothing else in the app needs to change.

Requires (see requirements.txt for version pins and the full rationale;
not installed automatically -- install these yourself):
    python -m pip install -r requirements.txt
    python -m pip install torch --index-url https://download.pytorch.org/whl/cpu

Models used (both public, no API key needed, downloaded from HF Hub
on first run and cached locally after):
  - j-hartmann/emotion-english-distilroberta-base
      7-way emotion classifier: anger, disgust, fear, joy, neutral,
      sadness, surprise. Mapped below to this app's 7 labels.
  - distilbert-base-uncased-finetuned-sst-2-english
      binary sentiment (POSITIVE/NEGATIVE) + score, used for the
      overall_sentiment / sentiment_score fields.

Why two small models instead of one: the emotion model doesn't
distinguish "Calm" from "Neutral" well on its own (no calm class), so
sentiment polarity + neutral-emotion is used to tell them apart -- a
mildly positive "neutral" reading becomes Calm, a genuinely flat one
stays Neutral. Everything else maps directly, EXCEPT "surprise" (see
_LABEL_MAP comment + the override in analyze()) -- surprise is
valence-ambiguous (a surprise party and a surprise bill are both
"surprise") so it is never assumed to be positive by default.
"""
from __future__ import annotations

from ml.emotion_analyzer import CRISIS_PATTERNS, EMOTIONS, EmotionAnalyzer
import re

# Lazy-loaded globally so the (relatively slow) model load only happens
# once per process, not once per request.
_emotion_pipe = None
_sentiment_pipe = None

# j-hartmann model's labels -> this app's EMOTIONS
_LABEL_MAP = {
    "anger": "Angry",
    "disgust": "Angry",
    "fear": "Anxious",
    "joy": "Happy",
    "neutral": "Neutral",     # refined to Calm below when sentiment is mildly positive
    "sadness": "Sad",
    # Conservative default: surprise is valence-ambiguous (could be
    # pleasant or unpleasant), so it does NOT auto-map to Happy. It's
    # treated as Neutral unless the sentiment model independently backs
    # up a positive read -- see the override in analyze() below.
    "surprise": "Neutral",
}

# How positive the (separate) sentiment score needs to be before a
# top-detected "surprise" gets promoted from Neutral to Happy. Set
# noticeably higher than the general positive/negative sentiment
# threshold (0.15) on purpose -- surprise needs real corroborating
# evidence, not just a mild lean, before we call it a happy surprise.
_SURPRISE_POSITIVE_SENTIMENT_THRESHOLD = 0.3



def _load_pipelines():
    global _emotion_pipe, _sentiment_pipe
    if _emotion_pipe is None:
        from transformers import pipeline
        _emotion_pipe = pipeline(
            "text-classification",
            model="j-hartmann/emotion-english-distilroberta-base",
            top_k=None,  # return all class scores, not just the top one
        )
        _sentiment_pipe = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
        )
    return _emotion_pipe, _sentiment_pipe


class TransformerEmotionAnalyzer(EmotionAnalyzer):
    def __init__(self, calm_threshold: float = 0.2):
        # If the top emotion is "neutral" but sentiment is at least this
        # positive, relabel as Calm instead of Neutral.
        self.calm_threshold = calm_threshold

    def analyze(self, text: str) -> dict:
        text = (text or "").strip()
        crisis_flag = any(re.search(p, text.lower()) for p in CRISIS_PATTERNS)

        if not text:
            return {
                "emotion_label": "Neutral", "confidence": 0.5,
                "overall_sentiment": "neutral", "sentiment_score": 0.0,
                "crisis_flag": crisis_flag, "scores": {},
            }

        emotion_pipe, sentiment_pipe = _load_pipelines()

        # transformers truncates long inputs automatically at the tokenizer
        # level for these pipelines, but cap defensively anyway.
        text = text[:2000]

        emotion_scores = emotion_pipe(text)[0]  # list of {label, score}
        emotion_scores = {e["label"]: round(float(e["score"]), 4) for e in emotion_scores}

        sentiment_result = sentiment_pipe(text)[0]  # {label: POSITIVE/NEGATIVE, score}
        raw_sentiment_score = float(sentiment_result["score"])
        sentiment_score = round(
            raw_sentiment_score if sentiment_result["label"] == "POSITIVE" else -raw_sentiment_score, 3
        )
        overall_sentiment = (
            "positive" if sentiment_score > 0.15 else
            "negative" if sentiment_score < -0.15 else
            "neutral"
        )

        top_raw_label = max(emotion_scores, key=emotion_scores.get)
        top_score = emotion_scores[top_raw_label]
        emotion_label = _LABEL_MAP.get(top_raw_label, "Neutral")

        # Conservative surprise handling (see _LABEL_MAP comment): only
        # promote to Happy when the independent sentiment score clearly
        # backs up a positive read. Otherwise it stays Neutral (and may
        # still be refined to Calm just below, same as any other Neutral).
        if top_raw_label == "surprise" and sentiment_score >= _SURPRISE_POSITIVE_SENTIMENT_THRESHOLD:
            emotion_label = "Happy"

        if emotion_label == "Neutral" and sentiment_score >= self.calm_threshold:
            emotion_label = "Calm"

        # Re-key scores to this app's 7 labels for the transparency payload
        mapped_scores = {e: 0.0 for e in EMOTIONS}
        for raw_label, score in emotion_scores.items():
            mapped = _LABEL_MAP.get(raw_label, "Neutral")
            mapped_scores[mapped] = max(mapped_scores[mapped], score)

        return {
            "emotion_label": emotion_label,
            "confidence": round(top_score, 3),
            "overall_sentiment": overall_sentiment,
            "sentiment_score": sentiment_score,
            "crisis_flag": crisis_flag,
            "scores": mapped_scores,
        }


def use_transformer_analyzer(calm_threshold: float = 0.2):
    """Call this once at app startup (e.g. in app.py's create_app) to
    switch the whole app over from the lexicon analyzer to this one:

        from ml.emotion_analyzer_transformer import use_transformer_analyzer
        use_transformer_analyzer()

    No other file needs to change -- ml/emotion_analyzer.analyze_journal_entry()
    calls whichever analyzer is currently set.
    """
    import ml.emotion_analyzer as base
    base._analyzer = TransformerEmotionAnalyzer(calm_threshold=calm_threshold)
