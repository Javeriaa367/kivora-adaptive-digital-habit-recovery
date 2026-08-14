"""
Loads the 4 production models trained by ml_pipeline/final_train.py and
exposes a single validated predict_all(form_dict) function for the Flask
routes to call. Models are loaded once at import time (fast startup,
no retraining on every request -- unlike the original app.py).
"""
import json
import os

import joblib
import numpy as np
import pandas as pd

ARTIFACTS_DIR = os.path.join(os.path.dirname(__file__), "artifacts")

# ---- Input schema -----------------------------------------------------
# Bounds observed in the training CSV, used to clamp (not reject) values
# from a direct/hand-crafted POST so a garbage extrapolated prediction
# can't be produced silently.
NUMERIC_BOUNDS = {
    "Daily_Usage_Hours": (0.0, 15.0),
    "Platforms_Used_Count": (1.0, 10.0),
    "Posts_Per_Week": (0.0, 20.0),
    "Notifications_Per_Day": (0.0, 200.0),
    "FOMO_Score": (0.0, 10.0),
    "Social_Comparison_Score": (0.0, 10.0),
    "Validation_Seeking_Score": (0.0, 10.0),
    "Scroll_Without_Purpose": (0.0, 10.0),
    "Sleep_Hours": (0.0, 14.0),
    "Offline_Relationship_Quality": (0.0, 10.0),
    "Physical_Activity_Hrs_Week": (0.0, 20.0),
    "Screen_Free_Time_Hrs": (0.0, 16.0),
}
BINARY_FIELDS = ["Late_Night_Usage", "Tried_To_Cut_Back", "Failed_To_Cut_Back"]
ORDINAL_CHOICES = {"First_Check_Morning": {0, 1, 2}}
PLATFORM_DUMMY_COLS = [
    "Platform_Instagram", "Platform_Snapchat", "Platform_TikTok",
    "Platform_Twitter/X", "Platform_YouTube",
]
KNOWN_PLATFORMS = {"Facebook", "Instagram", "Snapchat", "TikTok", "Twitter/X", "YouTube"}


class ValidationError(ValueError):
    pass


def _clamp_float(raw, field):
    try:
        val = float(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"'{field}' must be a number")
    lo, hi = NUMERIC_BOUNDS[field]
    return max(lo, min(hi, val))


def _binary(raw, field):
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        raise ValidationError(f"'{field}' must be 0 or 1")
    return 1 if val == 1 else 0


def _ordinal(raw, field):
    try:
        val = int(float(raw))
    except (TypeError, ValueError):
        raise ValidationError(f"'{field}' is invalid")
    allowed = ORDINAL_CHOICES[field]
    return val if val in allowed else min(allowed)


def build_feature_row(form: dict) -> pd.DataFrame:
    """Validate + clamp raw form input into the exact 21-column row the
    models were trained on. Raises ValidationError on unusable input."""
    row = {}
    for field in NUMERIC_BOUNDS:
        if field not in form:
            raise ValidationError(f"Missing field: {field}")
        row[field] = _clamp_float(form[field], field)

    for field in BINARY_FIELDS:
        if field not in form:
            raise ValidationError(f"Missing field: {field}")
        row[field] = _binary(form[field], field)

    row["First_Check_Morning"] = _ordinal(
        form.get("First_Check_Morning", 0), "First_Check_Morning"
    )

    platform = str(form.get("Primary_Platform", "")).strip()
    if platform not in KNOWN_PLATFORMS:
        platform = "Facebook"  # reference category (all-zero dummy vector)
    for col in PLATFORM_DUMMY_COLS:
        row[col] = 1 if col == f"Platform_{platform}" else 0

    return pd.DataFrame([row])


# ---- Model loading ------------------------------------------------------
_MODEL_FILES = {
    "addiction_risk_flag": "addiction_risk_flag.joblib",
    "addiction_level_detail": "addiction_level_detail.joblib",
    "wellbeing_score": "wellbeing_score.joblib",
    "wellbeing_risk_flag": "wellbeing_risk_flag.joblib",
}

_models = {}


def load_models():
    if _models:
        return _models
    for key, filename in _MODEL_FILES.items():
        path = os.path.join(ARTIFACTS_DIR, filename)
        _models[key] = joblib.load(path)
    return _models


def load_metadata() -> dict:
    with open(os.path.join(ARTIFACTS_DIR, "final_metadata.json")) as f:
        return json.load(f)


def predict_all(form: dict) -> dict:
    """Runs all 4 production models on one validated input row.
    Returns a JSON-serializable dict ready for the AJAX response."""
    models = load_models()
    X = build_feature_row(form)

    results = {}

    # -- Addiction risk flag (binary) --
    bundle = models["addiction_risk_flag"]
    Xs = bundle["scaler"].transform(X[bundle["features"]])
    proba = bundle["model"].predict_proba(Xs)[0]
    pred_idx = int(np.argmax(proba))
    results["addiction_risk_flag"] = {
        "label": bundle["classes"][pred_idx],
        "confidence": round(float(proba[pred_idx]), 3),
        "at_risk_probability": round(float(proba[1]), 3),
    }

    # -- Addiction level detail (4-class) --
    bundle = models["addiction_level_detail"]
    Xs = bundle["scaler"].transform(X[bundle["features"]])
    pred = bundle["model"].predict(Xs)[0]
    proba = bundle["model"].predict_proba(Xs)[0]
    class_probs = {c: round(float(p), 3) for c, p in zip(bundle["model"].classes_, proba)}
    results["addiction_level_detail"] = {
        "label": str(pred),
        "class_probabilities": class_probs,
    }

    # -- Wellbeing score (continuous) --
    bundle = models["wellbeing_score"]
    Xs = bundle["scaler"].transform(X[bundle["features"]])
    score = float(bundle["model"].predict(Xs)[0])
    results["wellbeing_score"] = {
        "value": round(max(0.0, min(10.0, score)), 2),
    }

    # -- Wellbeing risk flag (binary) --
    bundle = models["wellbeing_risk_flag"]
    Xs = bundle["scaler"].transform(X[bundle["features"]])
    proba = bundle["model"].predict_proba(Xs)[0]
    pred_idx = int(np.argmax(proba))
    results["wellbeing_risk_flag"] = {
        "label": bundle["classes"][pred_idx],
        "confidence": round(float(proba[pred_idx]), 3),
    }

    return results


# Targets it is safe to surface to a user. The 4-class addiction severity
# model (addiction_level_detail, ~57% accuracy) is deliberately excluded:
# a coin-flip classifier must never label a user "Severe" -- it is kept
# only for internal record and the transparency page.
USER_FACING_TARGETS = ("addiction_risk_flag", "wellbeing_score", "wellbeing_risk_flag")


def user_facing_results(results: dict) -> dict:
    """Return a copy of predict_all() output restricted to the targets that
    are safe for user-facing display / storage."""
    return {k: v for k, v in results.items() if k in USER_FACING_TARGETS}


# Warm the models at import time so the first request isn't slow
load_models()
