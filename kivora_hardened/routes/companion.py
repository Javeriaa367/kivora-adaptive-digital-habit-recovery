from flask import Blueprint, jsonify, render_template, request, session

from auth_utils import current_user, login_required
from ml.chatbot import GEMINI_API_KEY, get_companion_response

companion_bp = Blueprint("companion", __name__)

# Flask's default session is a signed client-side cookie. Keep only a short,
# clipped context window so normal conversation cannot make that cookie too
# large to persist in a browser.
MAX_HISTORY_TURNS = 2
MAX_HISTORY_MESSAGE_CHARS = 500
MAX_MESSAGE_LENGTH = 2000

# Simple in-process sliding-window rate limit -- no new dependency, and
# good enough for a single-worker deployment. Keyed by user_id so it
# survives across the companion page and any embedded use (e.g. the
# recovery plan's in-plan AI conversation activity), which both hit this
# same endpoint. Note: resets on process restart and isn't shared across
# multiple worker processes -- if this app is ever deployed with more than
# one worker, swap this for a shared store (e.g. Redis) instead.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_MESSAGES = 15
_rate_limit_hits: dict[int, list[float]] = {}


def _rate_limited(user_id: int) -> bool:
    import time
    now = time.time()
    hits = [t for t in _rate_limit_hits.get(user_id, []) if now - t < _RATE_LIMIT_WINDOW_SECONDS]
    hits.append(now)
    _rate_limit_hits[user_id] = hits
    return len(hits) > _RATE_LIMIT_MAX_MESSAGES

SUGGESTED_PROMPTS = [
    "Explain my last assessment results in simple terms",
    "I'm feeling stressed today, what can I try?",
    "Walk me through a breathing exercise",
    "What's a healthy way to cut back on screen time?",
]


def _history_turn(role: str, text: str) -> dict:
    """Bound server-supplied history before it reaches the session cookie."""
    return {"role": role, "text": text[:MAX_HISTORY_MESSAGE_CHARS]}


@companion_bp.route("/companion")
@login_required
def companion_page():
    return render_template(
        "companion.html", gemini_configured=bool(GEMINI_API_KEY), suggested_prompts=SUGGESTED_PROMPTS
    )


@companion_bp.route("/api/companion/send", methods=["POST"])
@login_required
def send_message():
    user_id = current_user()["id"]
    if _rate_limited(user_id):
        return jsonify({"ok": False, "error": "You're sending messages a bit fast -- please wait a moment and try again."}), 429

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "Message can't be empty."}), 400
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"ok": False, "error": "Keep messages under 2000 characters."}), 400

    history = session.get("companion_history", [])
    result = get_companion_response(history, message, user_id=user_id)

    if not result.get("crisis"):
        history.append(_history_turn("user", message))
        history.append(_history_turn("model", result["reply"]))
        session["companion_history"] = history[-(MAX_HISTORY_TURNS * 2):]

    return jsonify({"ok": True, **result})


@companion_bp.route("/api/companion/clear", methods=["POST"])
@login_required
def clear_history():
    session.pop("companion_history", None)
    return jsonify({"ok": True})
