"""
Explainable AI (Feature 4).

Every ML prediction gets: confidence, top contributing factors for THIS
specific input (not just the model's global feature importance), a plain-
language explanation, and explicit limitations -- never diagnostic
language.

Method, honestly disclosed per-target (no library like SHAP is available
in this environment, and adding one is a bigger dependency than this
warrants):

  - Linear models (addiction_risk_flag, addiction_level_detail,
    wellbeing_score are LogisticRegression/LinearRegression): true local
    contribution = coefficient x this user's standardized feature value.
    This is exact for a linear model, not an approximation -- it's the
    same arithmetic that produces the prediction, just decomposed
    per-feature.

  - Tree ensembles (wellbeing_risk_flag is RandomForestClassifier): no
    coefficients exist, so contribution = global feature_importances_ x
    |this user's standardized deviation from the training mean|. This is
    an approximation (labeled as such in the returned "method" field) --
    it highlights globally-important features that are also unusual for
    this specific user, which is a reasonable proxy but NOT a true local
    attribution like SHAP/TreeExplainer would give.

Reads metadata (ml/artifacts/final_metadata.json) already produced by the
training pipeline for global accuracy/confidence -- never re-derives or
invents a confidence number.
"""
import numpy as np

from ml.predictor import build_feature_row, load_metadata, load_models

FEATURE_LABELS = {
    "Daily_Usage_Hours": "daily usage hours",
    "Platforms_Used_Count": "number of platforms used",
    "Posts_Per_Week": "posts per week",
    "Notifications_Per_Day": "notifications per day",
    "FOMO_Score": "FOMO score",
    "Social_Comparison_Score": "social comparison score",
    "Validation_Seeking_Score": "validation-seeking score",
    "Scroll_Without_Purpose": "purposeless scrolling score",
    "Sleep_Hours": "sleep hours",
    "Offline_Relationship_Quality": "offline relationship quality",
    "Physical_Activity_Hrs_Week": "weekly physical activity hours",
    "Screen_Free_Time_Hrs": "screen-free time hours",
    "Late_Night_Usage": "late-night usage",
    "Tried_To_Cut_Back": "having tried to cut back",
    "Failed_To_Cut_Back": "a failed attempt to cut back",
    "First_Check_Morning": "how soon you check your phone after waking",
    "Platform_Instagram": "Instagram being your primary platform",
    "Platform_Snapchat": "Snapchat being your primary platform",
    "Platform_TikTok": "TikTok being your primary platform",
    "Platform_Twitter/X": "Twitter/X being your primary platform",
    "Platform_YouTube": "YouTube being your primary platform",
}

DIAGNOSIS_DISCLAIMER = (
    "This is a statistical estimate from a machine learning model trained on "
    "survey data, not a medical or psychological diagnosis. It does not "
    "account for your full life context."
)

TOP_FACTORS_LIMIT = 4


def _readable(feature: str) -> str:
    return FEATURE_LABELS.get(feature, feature.replace("_", " ").lower())


def _contributions_for_bundle(bundle, X, class_index=None):
    """Returns [(feature, signed_or_unsigned_contribution, method)] sorted
    by absolute magnitude, for one model bundle and one input row."""
    features = bundle["features"]
    Xs = bundle["scaler"].transform(X[features])[0]
    model = bundle["model"]

    if hasattr(model, "coef_"):
        coef = np.asarray(model.coef_)
        row = coef[class_index] if coef.ndim == 2 and class_index is not None else coef.reshape(-1)
        contributions = row * Xs
        method = "linear_coefficient"
    elif hasattr(model, "feature_importances_"):
        contributions = np.asarray(model.feature_importances_) * np.abs(Xs)
        method = "importance_weighted_deviation"
    else:
        contributions = np.zeros(len(features))
        method = "unavailable"

    ranked = sorted(zip(features, contributions), key=lambda t: abs(t[1]), reverse=True)
    return ranked[:TOP_FACTORS_LIMIT], method


def _factor_entries(ranked, method):
    out = []
    for feature, contribution in ranked:
        entry = {"feature": feature, "label": _readable(feature)}
        if method == "linear_coefficient":
            entry["direction"] = "increased" if contribution > 0 else "decreased"
        else:
            entry["direction"] = None  # magnitude-only for the approximate method
        out.append(entry)
    return out


def _simple_explanation(target_key: str, factors: list[dict], predicted_label: str) -> str:
    if not factors:
        return f"Not enough signal to explain this {target_key.replace('_', ' ')} prediction."
    top = factors[:2]
    parts = []
    for f in top:
        if f["direction"]:
            parts.append(f"{f['label']} {f['direction']} the estimate")
        else:
            parts.append(f"{f['label']} stood out as unusual for you")
    return f"'{predicted_label}' was driven mainly by: " + "; ".join(parts) + "."


def _limitations(target_meta: dict, method: str) -> str:
    conf = target_meta.get("confidence", "unknown")
    acc = target_meta.get("test_accuracy")
    lines = []
    if acc is not None:
        lines.append(f"This model tests at {acc*100:.0f}% accuracy on held-out data ({conf} confidence tier).")
    else:
        lines.append(f"This is a {conf}-confidence model with no single accuracy figure (it predicts a continuous score).")
    if method == "importance_weighted_deviation":
        lines.append("Contributing factors here are an approximation (importance x how unusual your value is), not an exact per-person breakdown.")
    lines.append(DIAGNOSIS_DISCLAIMER)
    return " ".join(lines)


def explain_all(form: dict) -> dict:
    """Mirrors predict_all()'s targets, one explanation block per target."""
    models = load_models()
    metadata = load_metadata()
    X = build_feature_row(form)
    explanations = {}

    # addiction_risk_flag: binary logistic regression
    bundle = models["addiction_risk_flag"]
    proba = bundle["model"].predict_proba(bundle["scaler"].transform(X[bundle["features"]]))[0]
    pred_idx = int(np.argmax(proba))
    ranked, method = _contributions_for_bundle(bundle, X, class_index=None)  # binary: coef_ has 1 row
    factors = _factor_entries(ranked, method)
    label = bundle["classes"][pred_idx]
    explanations["addiction_risk_flag"] = {
        "confidence": round(float(proba[pred_idx]), 3),
        "top_factors": factors,
        "explanation": _simple_explanation("addiction_risk_flag", factors, label),
        "limitations": _limitations(metadata["targets"]["addiction_risk_flag"], method),
        "method": method,
    }

    # addiction_level_detail: multiclass logistic regression
    bundle = models["addiction_level_detail"]
    Xs_full = bundle["scaler"].transform(X[bundle["features"]])
    proba = bundle["model"].predict_proba(Xs_full)[0]
    class_idx = int(np.argmax(proba))
    ranked, method = _contributions_for_bundle(bundle, X, class_index=class_idx)
    factors = _factor_entries(ranked, method)
    label = str(bundle["model"].classes_[class_idx])
    explanations["addiction_level_detail"] = {
        "confidence": round(float(proba[class_idx]), 3),
        "top_factors": factors,
        "explanation": _simple_explanation("addiction_level_detail", factors, label),
        "limitations": _limitations(metadata["targets"]["addiction_level_detail"], method),
        "method": method,
    }

    # wellbeing_score: linear regression, no class-probability confidence --
    # use the model's own metadata confidence tier instead of inventing one
    bundle = models["wellbeing_score"]
    ranked, method = _contributions_for_bundle(bundle, X, class_index=None)
    factors = _factor_entries(ranked, method)
    score = float(bundle["model"].predict(bundle["scaler"].transform(X[bundle["features"]]))[0])
    explanations["wellbeing_score"] = {
        "confidence": metadata["targets"]["wellbeing_score"].get("confidence", "unknown"),
        "top_factors": factors,
        "explanation": _simple_explanation("wellbeing_score", factors, f"{max(0.0, min(10.0, score)):.1f}/10"),
        "limitations": _limitations(metadata["targets"]["wellbeing_score"], method),
        "method": method,
    }

    # wellbeing_risk_flag: random forest, approximate local explanation
    bundle = models["wellbeing_risk_flag"]
    proba = bundle["model"].predict_proba(bundle["scaler"].transform(X[bundle["features"]]))[0]
    pred_idx = int(np.argmax(proba))
    ranked, method = _contributions_for_bundle(bundle, X, class_index=None)
    factors = _factor_entries(ranked, method)
    label = bundle["classes"][pred_idx]
    explanations["wellbeing_risk_flag"] = {
        "confidence": round(float(proba[pred_idx]), 3),
        "top_factors": factors,
        "explanation": _simple_explanation("wellbeing_risk_flag", factors, label),
        "limitations": _limitations(metadata["targets"]["wellbeing_risk_flag"], method),
        "method": method,
    }

    return explanations
