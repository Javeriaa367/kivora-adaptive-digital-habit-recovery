from flask import Blueprint, jsonify, render_template, request

from auth_utils import login_required
from ml.faq import answer_faq

faq_bp = Blueprint("faq", __name__)


@faq_bp.route("/faq")
@login_required
def faq_page():
    return render_template("faq.html")


@faq_bp.route("/api/faq", methods=["POST"])
@login_required
def ask_faq():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "Ask something first."}), 400
    if len(question) > 500:
        return jsonify({"ok": False, "error": "Keep questions under 500 characters."}), 400
    result = answer_faq(question)
    return jsonify({"ok": True, **result})
