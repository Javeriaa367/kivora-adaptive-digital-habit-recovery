from flask import Blueprint, jsonify, render_template, request

from auth_utils import current_user, login_required
from database.db import REFERRAL_PREMIUM_DAYS, get_referral_stats, list_testimonials, submit_feedback, submit_testimonial

feedback_bp = Blueprint("feedback", __name__)

MAX_MESSAGE_LENGTH = 2000


@feedback_bp.route("/feedback")
@login_required
def feedback_page():
    testimonials = list_testimonials(approved_only=True)
    referral = get_referral_stats(current_user()["id"])
    return render_template("feedback.html", testimonials=testimonials, referral=referral,
                           referral_days=REFERRAL_PREMIUM_DAYS)


@feedback_bp.route("/api/feedback", methods=["POST"])
@login_required
def submit():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    rating = data.get("rating")
    if not message:
        return jsonify({"ok": False, "error": "Feedback can't be empty."}), 400
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"ok": False, "error": "Message is too long."}), 400
    if rating is not None and (not isinstance(rating, int) or not (1 <= rating <= 5)):
        return jsonify({"ok": False, "error": "Rating must be 1-5."}), 400
    submit_feedback(current_user()["id"], message, rating)
    return jsonify({"ok": True})


@feedback_bp.route("/api/testimonial", methods=["POST"])
@login_required
def submit_testimonial_route():
    data = request.get_json(silent=True) or {}
    quote = (data.get("quote") or "").strip()
    if not quote:
        return jsonify({"ok": False, "error": "Testimonial can't be empty."}), 400
    if len(quote) > 500:
        return jsonify({"ok": False, "error": "Keep it under 500 characters."}), 400
    submit_testimonial(current_user()["id"], quote)
    return jsonify({"ok": True, "message": "Thanks! It'll show up publicly once reviewed."})
