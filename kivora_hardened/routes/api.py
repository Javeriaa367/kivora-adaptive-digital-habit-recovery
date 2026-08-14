from flask import Blueprint, jsonify, request

from auth_utils import current_user, login_required
from database.db import get_predictions_count_today, is_premium_user, save_prediction
from ml.coach import generate_wellness_report
from ml.explainability import explain_all
from ml.predictor import ValidationError, predict_all, user_facing_results
from ml.recommendations import get_recommendations
from ml.risk_engine import compute_risk_profile
from routes.billing import FREE_PLAN_DAILY_PREDICTION_LIMIT

api_bp = Blueprint("api", __name__)


@api_bp.route("/api/predict", methods=["POST"])
@login_required
def predict():
    user = current_user()

    if not is_premium_user(user):
        used_today = get_predictions_count_today(user["id"])
        if used_today >= FREE_PLAN_DAILY_PREDICTION_LIMIT:
            return jsonify({
                "ok": False,
                "error": f"You've used your {FREE_PLAN_DAILY_PREDICTION_LIMIT} free assessments for today. "
                         f"Upgrade to Premium for unlimited assessments.",
                "upgrade_required": True,
            }), 403

    form = request.get_json(silent=True) or request.form
    try:
        results = predict_all(form)
    except ValidationError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception:
        return jsonify({"ok": False, "error": "Something went wrong generating the prediction."}), 500

    results = user_facing_results(results)  # keep the 57% severity label off the wire and out of history
    save_prediction(user["id"], dict(form), results)
    # A check-in is new risk input. Persist one current snapshot now, rather
    # than leaving Risk Insights to show the last page-view snapshot.
    risk_profile = compute_risk_profile(user["id"], persist=True)
    recommendations = get_recommendations(results)
    coach_report = generate_wellness_report(results)
    try:
        explanations = explain_all(form)
        if explanations:
            explanations.pop("addiction_level_detail", None)
    except Exception:
        explanations = None  # never let explainability break the core prediction response
    return jsonify({
        "ok": True, "results": results,
        "recommendations": recommendations,
        "coach_report": coach_report,
        "explanations": explanations,
        "risk_profile": risk_profile,
    })
