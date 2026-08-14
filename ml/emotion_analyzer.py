"""
Journal emotion/sentiment analysis.

IMPORTANT — read before wiring this into anything clinical-sounding:
This is a lexicon/rule-based analyzer, not a trained NLP model. No network
access was available to install nltk/vaderSentiment/transformers in this
sandbox. It's a reasonable, transparent v1 (you can see exactly why it
classified something the way it did), but it WILL misread negation edge
cases, sarcasm, and mixed emotions. It should be labeled to users as
"detected mood" / "sentiment trend", never "diagnosis".

Swap path (recommended once you have network / an API budget):
  - Cheapest upgrade: `pip install vaderSentiment` and replace
    LexiconEmotionAnalyzer.analyze()'s sentiment half with
    SentimentIntensityAnalyzer().polarity_scores(text) -- same interface,
    better negation/degree handling, zero model download.
  - Better: call an LLM (this project already stubs that path in
    ml/chatbot.py) with a small classification prompt asking for one of
    the 7 emotion labels + confidence, and use that instead.
Either way, keep the EmotionAnalyzer interface below so routes/journal.py
doesn't need to change.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

EMOTIONS = ["Happy", "Calm", "Neutral", "Stressed", "Anxious", "Sad", "Angry"]

# Compact hand-built lexicons. Each word contributes 1 point to its emotion
# when present (after simple negation handling). Not exhaustive by design --
# small and auditable beats large and opaque for a v1 like this.
_LEXICON = {
    "Happy": ["happy", "glad", "great", "excited", "joy", "joyful", "grateful",
              "proud", "love", "loved", "fun", "awesome", "wonderful", "good",
              "amazing", "delighted", "cheerful", "hopeful", "optimistic"],
    "Calm": ["calm", "relaxed", "peaceful", "content", "fine", "okay", "ok",
             "steady", "grounded", "rested", "settled", "comfortable", "chill"],
    "Stressed": ["stressed", "overwhelmed", "busy", "pressure", "deadline",
                 "exhausted", "burnt out", "burned out", "tense", "rushed",
                 "swamped", "frazzled"],
    "Anxious": ["anxious", "worried", "nervous", "scared", "afraid", "panic",
                "uneasy", "restless", "dread", "on edge", "fear", "fearful"],
    "Sad": ["sad", "down", "depressed", "lonely", "hopeless", "empty", "cry",
            "crying", "tired", "numb", "hurt", "miserable", "heartbroken",
            "worthless"],
    "Angry": ["angry", "mad", "furious", "annoyed", "irritated", "frustrated",
              "rage", "resentful", "hate", "pissed"],
}

_NEGATORS = {"not", "no", "never", "n't", "without", "hardly", "barely"}

_POSITIVE_EMOTIONS = {"Happy", "Calm"}
_NEGATIVE_EMOTIONS = {"Stressed", "Anxious", "Sad", "Angry"}

# Phrases that should always surface the crisis banner regardless of
# emotion-score totals. Kept short and pattern-level on purpose --
# specific self-harm phrasing isn't enumerated here.
CRISIS_PATTERNS = [
    r"\bsuicid", r"\bkill myself\b", r"\bend my life\b", r"\bself.?harm",
    r"\bwant to die\b", r"\bno reason to live\b", r"\bhurt myself\b",
]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


class EmotionAnalyzer(ABC):
    @abstractmethod
    def analyze(self, text: str) -> dict:
        """Returns:
        {
          "emotion_label": one of EMOTIONS,
          "confidence": float 0-1,
          "overall_sentiment": "positive" | "neutral" | "negative",
          "sentiment_score": float -1..1,
          "crisis_flag": bool,
          "scores": {emotion: raw_score, ...}  # for transparency/debugging
        }
        """
        raise NotImplementedError


class LexiconEmotionAnalyzer(EmotionAnalyzer):
    def analyze(self, text: str) -> dict:
        text = text or ""
        lower = text.lower()

        crisis_flag = any(re.search(p, lower) for p in CRISIS_PATTERNS)

        tokens = _tokenize(text)
        scores = {e: 0.0 for e in EMOTIONS if e != "Neutral"}

        for i, tok in enumerate(tokens):
            negated = i > 0 and tokens[i - 1] in _NEGATORS
            for emotion, words in _LEXICON.items():
                if tok in words:
                    if negated:
                        # crude negation: flip within the same valence family
                        flipped = "Sad" if emotion in _POSITIVE_EMOTIONS else "Calm"
                        scores[flipped] = scores.get(flipped, 0) + 0.5
                    else:
                        scores[emotion] += 1.0

        total_signal = sum(scores.values())
        if total_signal == 0:
            emotion_label = "Neutral"
            confidence = 0.5
        else:
            emotion_label = max(scores, key=scores.get)
            confidence = round(min(0.95, 0.4 + scores[emotion_label] / (total_signal + 2)), 2)

        pos = sum(scores[e] for e in _POSITIVE_EMOTIONS)
        neg = sum(scores[e] for e in _NEGATIVE_EMOTIONS)
        if pos + neg == 0:
            sentiment_score = 0.0
        else:
            sentiment_score = round((pos - neg) / (pos + neg), 2)

        overall_sentiment = (
            "positive" if sentiment_score > 0.15 else
            "negative" if sentiment_score < -0.15 else
            "neutral"
        )

        return {
            "emotion_label": emotion_label,
            "confidence": confidence,
            "overall_sentiment": overall_sentiment,
            "sentiment_score": sentiment_score,
            "crisis_flag": crisis_flag,
            "scores": scores,
        }


_analyzer: EmotionAnalyzer = LexiconEmotionAnalyzer()


def analyze_journal_entry(text: str) -> dict:
    return _analyzer.analyze(text)


EMOTION_META = {
    "Happy":    {"emoji": "\U0001F60A", "color": "teal"},
    "Calm":     {"emoji": "\U0001F642", "color": "teal"},
    "Neutral":  {"emoji": "\U0001F610", "color": "slate"},
    "Stressed": {"emoji": "\U0001F62B", "color": "amber"},
    "Anxious":  {"emoji": "\U0001F630", "color": "amber"},
    "Sad":      {"emoji": "\U0001F622", "color": "coral"},
    "Angry":    {"emoji": "\U0001F620", "color": "coral"},
}
