"""
Regression test (production-readiness audit pass): the Transformer+VADER
confidence-agreement check in HybridEmotionAnalyzer._analyze_inner()
previously only recognized positive-positive or negative-negative as
"the two engines agree" -- a case where both engines independently landed
on Neutral/neutral fell through as a *disagreement* and had its
confidence docked by 0.05, even though the two engines fully agreed.

These tests inject fake sub-analyzers directly (bypassing the real
VADER/transformer model loads, which aren't installed in every test
environment) so the combination logic itself can be exercised
deterministically.
"""
from ml.emotion_analyzer_hybrid import HybridEmotionAnalyzer


class _FakeSubAnalyzer:
    """Minimal stand-in for VaderEmotionAnalyzer / TransformerEmotionAnalyzer
    -- only .analyze(text) is used by HybridEmotionAnalyzer."""

    def __init__(self, result: dict):
        self._result = result

    def analyze(self, text: str) -> dict:
        return dict(self._result)


def _make_hybrid(transformer_result: dict, vader_result: dict) -> HybridEmotionAnalyzer:
    analyzer = HybridEmotionAnalyzer()
    # Bypass the lazy _get_vader()/_get_transformer() loaders (which would
    # otherwise try to import vaderSentiment/transformers) by setting the
    # already-loaded instance directly -- same sentinel contract the real
    # loaders use ("not None" = ready).
    analyzer._transformer = _FakeSubAnalyzer(transformer_result)
    analyzer._vader = _FakeSubAnalyzer(vader_result)
    return analyzer


def test_mutual_neutral_read_is_treated_as_agreement():
    """Both engines independently say 'nothing going on here' -- that
    agreement should nudge confidence UP, not down."""
    transformer_result = {
        "emotion_label": "Neutral", "confidence": 0.6,
        "overall_sentiment": "neutral", "sentiment_score": 0.0,
        "crisis_flag": False, "scores": {"Neutral": 0.6},
    }
    vader_result = {
        "emotion_label": "Neutral", "confidence": 0.55,
        "overall_sentiment": "neutral", "sentiment_score": 0.01,
        "crisis_flag": False, "scores": {"positive": 0.1, "negative": 0.1, "neutral": 0.8},
    }
    analyzer = _make_hybrid(transformer_result, vader_result)

    result = analyzer.analyze("Nothing much happened today, same as usual, a pretty ordinary day overall.")

    # Base transformer confidence was 0.6; mutual agreement should push it
    # up toward 0.65 (capped at 0.97), never down.
    assert result["confidence"] >= 0.6

