"""
Regression test (production-readiness audit pass): a brand-new account
with zero journal entries, zero predictions, and zero habit check-ins
previously got the exact same "No elevated <category> risk signals right
now" wording as a long-time user whose history is consistently calm.
Both cases produced an empty `reasons` list, so they were indistinguishable
in the explanation text -- which reads as false reassurance for someone
the app simply hasn't observed yet.

This does NOT change any score or level -- a user with no data still
correctly gets score=0 / level="low" for every category. Only the
explanation *wording* for the zero-reasons case now depends on whether
there was any underlying data to look at.
"""
from ml.risk_engine import compute_risk_profile, generate_risk_explanation


def test_brand_new_user_gets_insufficient_evidence_wording(app, make_user):
    user_id = make_user()
    with app.app_context():
        profile = compute_risk_profile(user_id, persist=False)

    for category, result in profile.items():
        assert result["score"] == 0
        assert result["level"] == "low"
        assert result["reasons"] == []
        assert "not enough" in result["explanation"].lower()
        assert "no elevated" not in result["explanation"].lower()


def test_calm_history_still_gets_reassurance_wording_not_insufficient_evidence():
    """Contrast case: reasons is empty AND there IS evidence (has_evidence=True)
    -- must keep today's exact reassurance wording, not the new one."""
    explanation = generate_risk_explanation("depression", "low", [], has_evidence=True)
    assert explanation == "No elevated depression risk signals right now."


def test_no_evidence_wording_is_distinct_and_backward_compatible_default():
    # Default (no has_evidence argument) must match pre-fix behavior exactly,
    # so any other/older caller is unaffected.
    assert generate_risk_explanation("anxiety", "low", []) == (
        "No elevated anxiety risk signals right now."
    )
    no_evidence = generate_risk_explanation("anxiety", "low", [], has_evidence=False)
    assert no_evidence != "No elevated anxiety risk signals right now."
    assert "anxiety" in no_evidence.lower()
