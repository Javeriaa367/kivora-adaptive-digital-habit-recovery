"""Small standalone tools: what-if simulator, journal word cloud."""
from collections import Counter
import re

from flask import Blueprint, jsonify, render_template, request

from auth_utils import current_user, login_required
from database.db import get_journal_entries
from ml.predictor import NUMERIC_BOUNDS, ValidationError, build_feature_row, load_models

tools_bp = Blueprint("tools", __name__)

_STOPWORDS = {
    "the","a","an","and","or","but","is","are","was","were","be","been","being",
    "to","of","in","on","at","for","with","as","by","that","this","it","i","my",
    "me","we","our","you","your","he","she","they","them","so","just","really",
    "very","today","feel","feeling","felt","am","im","its","not","no","have",
    "had","has","do","did","does","about","if","than","then","some","all",
}


@tools_bp.route("/simulator")
@login_required
def simulator_page():
    return render_template("simulator.html", bounds=NUMERIC_BOUNDS)


@tools_bp.route("/api/simulate", methods=["POST"])
@login_required
def simulate():
    """Holds all inputs fixed except one field, sweeps it across its valid
    range, and returns what the ALREADY-TRAINED models predict at each
    point. This is NOT a time-series forecast -- it's the model's
    sensitivity to one input, honestly framed as 'what the model predicts
    if this were different', not 'what will happen in 30 days'."""
    data = request.get_json(silent=True) or {}
    base_inputs = data.get("inputs", {})
    field = data.get("field")

    if field not in NUMERIC_BOUNDS:
        return jsonify({"ok": False, "error": f"'{field}' isn't a sweepable numeric field."}), 400

    lo, hi = NUMERIC_BOUNDS[field]
    steps = 12
    values = [round(lo + (hi - lo) * i / (steps - 1), 2) for i in range(steps)]

    models = load_models()
    points = []
    for v in values:
        trial_inputs = dict(base_inputs)
        trial_inputs[field] = v
        try:
            X = build_feature_row(trial_inputs)
        except ValidationError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        bundle = models["wellbeing_score"]
        Xs = bundle["scaler"].transform(X[bundle["features"]])
        wb = float(bundle["model"].predict(Xs)[0])

        bundle = models["addiction_risk_flag"]
        Xs = bundle["scaler"].transform(X[bundle["features"]])
        risk_proba = float(bundle["model"].predict_proba(Xs)[0][1])

        points.append({"value": v, "wellbeing_score": round(max(0, min(10, wb)), 2),
                        "at_risk_probability": round(risk_proba, 3)})

    return jsonify({"ok": True, "field": field, "points": points})


@tools_bp.route("/api/journal/word-frequencies")
@login_required
def word_frequencies():
    entries = get_journal_entries(current_user()["id"], limit=200)
    words = []
    for e in entries:
        tokens = re.findall(r"[a-zA-Z']+", e["entry_text"].lower())
        words.extend(t for t in tokens if len(t) > 2 and t not in _STOPWORDS)
    counts = Counter(words).most_common(30)
    return jsonify({"ok": True, "words": [{"word": w, "count": c} for w, c in counts]})
