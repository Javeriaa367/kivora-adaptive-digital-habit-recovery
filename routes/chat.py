from flask import Blueprint, jsonify, request

from auth_utils import current_user, login_required
from ml.chatbot import get_chatbot_response

chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/api/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "Message can't be empty."}), 400
    if len(message) > 2000:
        return jsonify({"ok": False, "error": "Message is too long."}), 400

    result = get_chatbot_response(message, user_id=current_user()["id"])
    return jsonify({"ok": True, **result})
