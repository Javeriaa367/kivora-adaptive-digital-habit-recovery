"""
VADER-based context-aware sentiment analyzer -- upgrade from the pure
hand-built lexicon in ml/emotion_analyzer.py.

Why VADER over the original lexicon approach: VADER (Hutto & Gilbert,
2014) handles negation ("not good"), intensity/degree modifiers ("very
sad" vs "sad"), punctuation emphasis ("great!!!"), capitalization
("AMAZING"), and contrastive conjunctions ("but") -- none of which the
hand-rolled version accounted for. It's still a lexicon/rule-based tool
underneath (not a trained model), so it will still miss things like irony
or nuanced narrative context ("she started crying" -- is that sad or
relieved?), but it's a well-validated, widely-used step up from ad hoc
word lists, and it's the standard baseline this kind of feature is judged
against.

Architecture note for the "easily upgradable" requirement: this class
implements the same EmotionAnalyzer interface as the other two analyzers
in this package (lexicon, transformer). Swapping to Gemini-based emotion
classification later means adding one more class with the same
.analyze(text) -> dict signature and pointing use_vader_analyzer() /
use_transformer_analyzer() at it -- nothing else in the app changes.

Requires (not installed in this sandbox -- no network):
    pip install vaderSentiment
"""
from __future__ import annotations

import re

from ml.emotion_analyzer import CRISIS_PATTERNS, EMOTIONS, EmotionAnalyzer

_analyzer_instance = None


def _load_vader():
    global _analyzer_instance
    if _analyzer_instance is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _analyzer_instance = SentimentIntensityAnalyzer()
    return _analyzer_instance


# 8-state emotion word groups (Happiness, Sadness, Anxiety, Anger, Stress,
# Fear, Calmness, Hopefulness) layered ON TOP of VADER's polarity score --
# VADER gives strong pos/neg/neutral, but doesn't distinguish WHICH negative
# emotion. This layer picks the most-matched emotion word group, then lets
# VADER's compound score set the confidence and break Neutral/Calm ties,
# instead of the group doing double duty for both jobs like the original
# lexicon analyzer did.
_EMOTION_GROUPS = {
    "Happiness": ["happy", "glad", "joy", "joyful", "excited", "delighted", "cheerful", "grateful", "proud", "love"],
    "Sadness": ["sad", "down", "depressed", "lonely", "hopeless", "empty", "cry", "crying", "heartbroken", "miserable"],
    "Anxiety": ["anxious", "nervous", "worried", "uneasy", "restless", "on edge", "panicked", "apprehensive"],
    "Anger": ["angry", "furious", "mad", "irritated", "annoyed", "frustrated", "resentful", "pissed"],
    "Stress": ["stressed", "overwhelmed", "swamped", "burnt out", "burned out", "pressured", "exhausted", "frazzled"],
    "Fear": ["afraid", "scared", "fear", "terrified", "frightened", "dread"],
    "Calmness": ["calm", "relaxed", "peaceful", "content", "steady", "grounded", "at ease"],
    "Hopefulness": ["hopeful", "optimistic", "looking forward", "excited about", "confident", "encouraged"],
}

# Map the 8 fine-grained states down to this app's existing 7-label schema
# (Happy/Calm/Neutral/Stressed/Anxious/Sad/Angry) so journal history,
# badges, and the dashboard's mood distribution chart keep working
# unchanged. `fine_emotion` is included separately in the result for
# anywhere that wants the richer 8-state label.
_FINE_TO_APP_LABEL = {
    "Happiness": "Happy", "Sadness": "Sad", "Anxiety": "Anxious", "Anger": "Angry",
    "Stress": "Stressed", "Fear": "Anxious", "Calmness": "Calm", "Hopefulness": "Happy",
}


class VaderEmotionAnalyzer(EmotionAnalyzer):
    def analyze(self, text: str) -> dict:
        text = (text or "").strip()
        crisis_flag = any(re.search(p, text.lower()) for p in CRISIS_PATTERNS)

        if not text:
            return {
                "emotion_label": "Neutral", "confidence": 0.5, "overall_sentiment": "neutral",
                "sentiment_score": 0.0, "crisis_flag": crisis_flag, "scores": {},
                "fine_emotion": "Neutral",
            }

        vader = _load_vader()
        scores = vader.polarity_scores(text)
        compound = scores["compound"]  # -1..1, VADER's normalized overall score

        overall_sentiment = "positive" if compound > 0.05 else "negative" if compound < -0.05 else "neutral"

        lower = text.lower()
        group_matches = {
            group: sum(1 for w in words if w in lower) for group, words in _EMOTION_GROUPS.items()
        }
        top_group = max(group_matches, key=group_matches.get)
        has_signal = group_matches[top_group] > 0

        if has_signal:
            fine_emotion = top_group
        elif overall_sentiment == "positive":
            fine_emotion = "Calmness"
        elif overall_sentiment == "negative":
            fine_emotion = "Sadness"
        else:
            fine_emotion = "Neutral" if abs(compound) < 0.05 else ("Happiness" if compound > 0 else "Sadness")

        emotion_label = _FINE_TO_APP_LABEL.get(fine_emotion, "Neutral")
        confidence = round(min(0.95, 0.5 + abs(compound) * 0.5 + (0.1 if has_signal else 0)), 2)

        return {
            "emotion_label": emotion_label,
            "fine_emotion": fine_emotion,
            "confidence": confidence,
            "overall_sentiment": overall_sentiment,
            "sentiment_score": round(compound, 3),
            "crisis_flag": crisis_flag,
            "scores": {"positive": scores["pos"], "negative": scores["neg"], "neutral": scores["neu"]},
        }


def use_vader_analyzer():
    """Call once at startup to switch the whole app to VADER:

        from ml.emotion_analyzer_vader import use_vader_analyzer
        use_vader_analyzer()

    Requires `pip install vaderSentiment` first. No other file changes --
    same pattern as use_transformer_analyzer() in
    ml/emotion_analyzer_transformer.py.
    """
    import ml.emotion_analyzer as base
    base._analyzer = VaderEmotionAnalyzer()
