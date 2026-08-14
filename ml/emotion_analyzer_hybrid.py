"""
Hybrid Journal emotion/sentiment analyzer.

Combines three signals, each used for the sub-task it's actually good at
instead of being blindly averaged together:

  - TransformerEmotionAnalyzer (ml/emotion_analyzer_transformer.py)
    -- primary driver of EMOTION classification (which mood: Happy / Sad /
    Anxious / Stressed / Angry / Calm / Neutral), and of the "secondary
    mood" shown for mixed entries. It's a trained 7-way classifier, so
    it's better at "which emotion" than a sentiment tool is.

  - VaderEmotionAnalyzer (ml/emotion_analyzer_vader.py)
    -- fallback driver of overall SENTIMENT / polarity when the Transformer
    is unavailable. Its native positive/neutral/negative distribution is
    retained as auxiliary context when both engines are available; it is
    never presented as a Transformer probability distribution.

  - LexiconEmotionAnalyzer (ml/emotion_analyzer.py)
    -- always-available fallback/support signal, with zero external
    dependencies. Used alone if neither of the above can load, and used
    to help decide secondary mood when the transformer is unavailable.

Fallback hierarchy (never raises -- see analyze() docstring):
    transformer + VADER available   -> Transformer emotion/sentiment + VADER auxiliary distribution
    only VADER available            -> VADER (sentiment + emotion) + lexical support
    only transformer available      -> Transformer (emotion + sentiment) + lexical support
    neither available                -> lexical only
    literally anything else fails    -> safe neutral result, never a crash

Nothing here touches the network or loads a model at import time or at
__init__ time. Both the transformer and VADER are attempted lazily, inside
try/except, the first time analyze() actually needs them -- and cached on
the instance afterwards, so a model is loaded at most once per process,
not once per request (see _get_vader / _get_transformer).
"""
from __future__ import annotations

import logging

from ml.emotion_analyzer import (
    CRISIS_PATTERNS,
    EMOTIONS,
    EmotionAnalyzer,
    LexiconEmotionAnalyzer,
    _tokenize,
)
import re

logger = logging.getLogger(__name__)

_POSITIVE_EMOTIONS = {"Happy", "Calm"}

# A second emotion is only surfaced in the UI ("Also detected: Hopeful")
# when it has real signal of its own -- otherwise almost every entry would
# show a meaningless secondary mood.
_SECONDARY_EMOTION_MIN_SCORE = 0.20

# Very short entries ("Fine.", "Bad day.") don't carry enough signal for a
# confident read no matter which engine is used -- cap confidence and let
# the UI communicate uncertainty instead of a falsely precise number.
_SHORT_ENTRY_TOKEN_COUNT = 4
_SHORT_ENTRY_CONFIDENCE_CAP = 0.6

# Thresholds for confidence_label() below -- kept in one place so the
# wording and the cutoffs stay next to each other.
_CONFIDENCE_LABEL_STRONG = 0.75
_CONFIDENCE_LABEL_MODERATE = 0.55


def confidence_label(confidence: float, low_confidence: bool = False) -> str:
    """Non-clinical, student-facing wording for a raw confidence float.

    The transformer's per-class probability and VADER's compound score
    are NOT statistically calibrated confidence intervals -- they're raw
    model outputs. Showing "82%" next to a mood label reads as more
    precise/clinical than that number actually is, so the Journal UI
    should show one of these three phrases instead of (or alongside, in
    smaller print) the raw percentage. The numeric confidence is still
    kept in the result dict for anyone who wants it (debugging, future
    analytics) -- this function only governs the wording, not the value.
    """
    if low_confidence or confidence < _CONFIDENCE_LABEL_MODERATE:
        return "Low confidence"
    if confidence < _CONFIDENCE_LABEL_STRONG:
        return "Moderate signal"
    return "Strong signal"


class HybridEmotionAnalyzer(EmotionAnalyzer):
    """See module docstring for the combination strategy."""

    def __init__(self):
        self._lexical = LexiconEmotionAnalyzer()
        # Sentinel states: None = "not attempted yet", False = "attempted
        # and unavailable", instance = "loaded and ready". This means the
        # (potentially slow) load is attempted at most once per process.
        self._vader = None
        self._transformer = None

    # -- lazy sub-analyzer loaders, each isolated so one failing never
    #    takes the other down with it -----------------------------------
    def _get_vader(self):
        if self._vader is None:
            try:
                from ml.emotion_analyzer_vader import VaderEmotionAnalyzer
                inst = VaderEmotionAnalyzer()
                inst.analyze("warmup")  # forces the lazy model load now, surfaces import/runtime errors here rather than mid-request
                self._vader = inst
            except Exception as exc:
                logger.warning("VADER analyzer unavailable (%s: %s) -- continuing without it.", type(exc).__name__, exc)
                self._vader = False
        return self._vader or None

    def _get_transformer(self):
        if self._transformer is None:
            try:
                from ml.emotion_analyzer_transformer import TransformerEmotionAnalyzer
                inst = TransformerEmotionAnalyzer()
                inst.analyze("warmup")  # forces the (slow, one-time) HF model download/load now, cached on this instance after
                self._transformer = inst
            except Exception as exc:
                logger.warning("Transformer analyzer unavailable (%s: %s) -- continuing without it.", type(exc).__name__, exc)
                self._transformer = False
        return self._transformer or None

    def warm_up(self):
        """Optional: call once at app startup (off the request path) so the
        first real journal submission isn't the one paying for model
        download/load time. Safe to call even if the optional deps aren't
        installed -- failures are swallowed the same way analyze() does."""
        self._get_vader()
        self._get_transformer()

    # -- main entry point --------------------------------------------
    def analyze(self, text: str) -> dict:
        text = (text or "").strip()
        crisis_flag = any(re.search(p, text.lower()) for p in CRISIS_PATTERNS)

        if not text:
            return self._safe_neutral_result(crisis_flag)

        try:
            return self._analyze_inner(text, crisis_flag)
        except Exception:
            # Absolute last resort. Whatever went wrong above, the Journal
            # must still return something usable rather than a 500.
            logger.error("Hybrid journal analysis failed unexpectedly -- returning safe fallback.", exc_info=True)
            try:
                lexical = self._lexical.analyze(text)
                lexical["analysis_engine"] = "lexical_only"
                lexical.setdefault("secondary_emotion", None)
                lexical.setdefault("sentiment_breakdown", self._breakdown_from_lexical(lexical))
                lexical.setdefault("low_confidence", True)
                return lexical
            except Exception:
                return self._safe_neutral_result(crisis_flag)

    # -- combination logic ---------------------------------------------
    def _analyze_inner(self, text: str, crisis_flag: bool) -> dict:
        lexical_result = self._lexical.analyze(text)

        transformer_result = None
        transformer = self._get_transformer()
        if transformer is not None:
            try:
                transformer_result = transformer.analyze(text)
            except Exception:
                logger.warning("Transformer inference failed on this entry -- falling back for this request.", exc_info=True)

        vader_result = None
        vader = self._get_vader()
        if vader is not None:
            try:
                vader_result = vader.analyze(text)
            except Exception:
                logger.warning("VADER inference failed on this entry -- falling back for this request.", exc_info=True)

        engines_used = ["lexical"]

        # ---- primary emotion: transformer > vader > lexical ----
        if transformer_result:
            emotion_label = transformer_result["emotion_label"]
            emotion_scores = transformer_result["scores"]  # mapped to the app's 7 labels, probabilities
            emotion_confidence = transformer_result["confidence"]
            engines_used.append("transformer")
        elif vader_result:
            emotion_label = vader_result["emotion_label"]
            emotion_scores = lexical_result["scores"]  # transformer not available; lexical scores are the richest emotion breakdown we have
            emotion_confidence = vader_result["confidence"]
            engines_used.append("vader")
        else:
            emotion_label = lexical_result["emotion_label"]
            emotion_scores = lexical_result["scores"]
            emotion_confidence = lexical_result["confidence"]

        # ---- overall sentiment/polarity: transformer > vader > lexical ----
        # The Transformer's binary classifier is authoritative whenever it
        # successfully analyzed the entry. VADER's pos/neu/neg values are a
        # different model's distribution, so keep them only as explicitly
        # labeled auxiliary context rather than using them to override or
        # fabricate Transformer probabilities.
        if transformer_result:
            overall_sentiment = transformer_result["overall_sentiment"]
            sentiment_score = transformer_result["sentiment_score"]
            if vader_result:
                sentiment_breakdown = dict(vader_result["scores"])
                sentiment_breakdown_source = "vader_auxiliary"
                if "vader" not in engines_used:
                    engines_used.append("vader")
            else:
                sentiment_breakdown = None
                sentiment_breakdown_source = None
        elif vader_result:
            overall_sentiment = vader_result["overall_sentiment"]
            sentiment_score = vader_result["sentiment_score"]
            sentiment_breakdown = dict(vader_result["scores"])
            sentiment_breakdown_source = "vader"
            if "vader" not in engines_used:
                engines_used.append("vader")
        else:
            overall_sentiment = lexical_result["overall_sentiment"]
            sentiment_score = lexical_result["sentiment_score"]
            sentiment_breakdown = self._breakdown_from_lexical(lexical_result)
            sentiment_breakdown_source = "lexical_derived"

        # ---- confidence: start from the engine that set emotion_label,
        # nudge up slightly when engines agree on valence, and cap for
        # very short entries so we don't report false precision ----
        confidence = emotion_confidence
        if vader_result and transformer_result:
            transformer_positive = transformer_result["emotion_label"] in _POSITIVE_EMOTIONS
            transformer_neutral = transformer_result["emotion_label"] == "Neutral"
            transformer_negative = not transformer_positive and not transformer_neutral
            vader_positive = vader_result["overall_sentiment"] == "positive"
            vader_neutral = vader_result["overall_sentiment"] == "neutral"
            vader_negative = vader_result["overall_sentiment"] == "negative"
            # Two engines calling the SAME entry neutral is agreement too --
            # without this case, a mutually-neutral read was previously
            # scored as a disagreement (neither positive-positive nor
            # negative-negative matched) and had its confidence needlessly
            # docked, which is backwards: agreeing it's neutral is still
            # agreement.
            agree = (
                (transformer_positive and vader_positive)
                or (transformer_negative and vader_negative)
                or (transformer_neutral and vader_neutral)
            )
            confidence = min(0.97, confidence + 0.05) if agree else max(0.3, confidence - 0.05)

        token_count = len(_tokenize(text))
        low_confidence = token_count <= _SHORT_ENTRY_TOKEN_COUNT
        if low_confidence:
            confidence = min(confidence, _SHORT_ENTRY_CONFIDENCE_CAP)

        confidence = round(max(0.05, min(0.97, confidence)), 2)

        # ---- secondary/mixed emotion, from whichever score breakdown we
        # actually have (transformer's real probabilities are best; lexical
        # raw counts are the fallback when the transformer isn't available) ----
        secondary_emotion = self._pick_secondary_emotion(emotion_label, emotion_scores)

        return {
            "emotion_label": emotion_label,
            "secondary_emotion": secondary_emotion,
            "confidence": confidence,
            "overall_sentiment": overall_sentiment,
            "sentiment_score": sentiment_score,
            "crisis_flag": crisis_flag,
            "scores": {e: round(float(emotion_scores.get(e, 0.0)), 4) for e in EMOTIONS},
            "sentiment_breakdown": (
                {k: round(float(v), 4) for k, v in sentiment_breakdown.items()}
                if sentiment_breakdown is not None else None
            ),
            "sentiment_breakdown_source": sentiment_breakdown_source,
            "low_confidence": low_confidence,
            "analysis_engine": "+".join(engines_used),
        }

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _pick_secondary_emotion(primary: str, scores: dict) -> str | None:
        if not scores:
            return None
        ranked = sorted(
            ((label, score) for label, score in scores.items() if label not in (primary, "Neutral")),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if not ranked:
            return None
        top_label, top_score = ranked[0]
        if top_score >= _SECONDARY_EMOTION_MIN_SCORE:
            return top_label
        return None

    @staticmethod
    def _breakdown_from_lexical(lexical_result: dict) -> dict:
        scores = lexical_result.get("scores", {})
        pos = sum(v for k, v in scores.items() if k in _POSITIVE_EMOTIONS)
        neg = sum(v for k, v in scores.items() if k not in _POSITIVE_EMOTIONS)
        total = pos + neg
        if total == 0:
            return {"positive": 0.0, "neutral": 1.0, "negative": 0.0}
        # Signal strength (how much of the entry mattered at all) sets how
        # much of the pie is "neutral" vs. carved up between pos/neg.
        neutral = max(0.0, 1.0 - min(1.0, total / 4.0))
        remainder = 1.0 - neutral
        return {
            "positive": remainder * (pos / total),
            "neutral": neutral,
            "negative": remainder * (neg / total),
        }

    @staticmethod
    def _breakdown_from_signed_score(sentiment_score: float) -> dict:
        # Best-effort breakdown when only a single signed score (no native
        # pos/neu/neg triple) is available, e.g. transformer-only mode.
        magnitude = min(1.0, abs(sentiment_score))
        neutral = 1.0 - magnitude
        if sentiment_score >= 0:
            return {"positive": magnitude, "neutral": neutral, "negative": 0.0}
        return {"positive": 0.0, "neutral": neutral, "negative": magnitude}

    @staticmethod
    def _safe_neutral_result(crisis_flag: bool) -> dict:
        return {
            "emotion_label": "Neutral",
            "secondary_emotion": None,
            "confidence": 0.5,
            "overall_sentiment": "neutral",
            "sentiment_score": 0.0,
            "crisis_flag": crisis_flag,
            "scores": {e: 0.0 for e in EMOTIONS},
            "sentiment_breakdown": {"positive": 0.0, "neutral": 1.0, "negative": 0.0},
            "sentiment_breakdown_source": "safe_neutral",
            "low_confidence": True,
            "analysis_engine": "none",
        }


def use_hybrid_analyzer(warm_up: bool = False) -> HybridEmotionAnalyzer:
    """Call once at app startup to switch the whole app over to the hybrid
    analyzer:

        from ml.emotion_analyzer_hybrid import use_hybrid_analyzer
        use_hybrid_analyzer()

    No other file needs to change -- ml/emotion_analyzer.analyze_journal_entry()
    calls whichever analyzer is currently set (same swap pattern as
    use_vader_analyzer() / use_transformer_analyzer()).

    warm_up=True eagerly attempts to load VADER/the transformer right away
    (still safely -- failures are swallowed) instead of waiting for the
    first real journal submission to pay that cost.
    """
    import ml.emotion_analyzer as base
    instance = HybridEmotionAnalyzer()
    base._analyzer = instance
    if warm_up:
        instance.warm_up()
    return instance
