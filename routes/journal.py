from flask import Blueprint, jsonify, render_template, request

from auth_utils import current_user, login_required
from database.db import get_journal_entries, save_journal_entry
from ml.emotion_analyzer import EMOTION_META, analyze_journal_entry
from ml.emotion_analyzer_hybrid import confidence_label
from ml.emotion_explainer import generate_emotion_explanation
from ml.memory import generate_pattern_insight, update_memory_from_entry
from ml.recommendations import get_recommendations
from ml.crisis_resources import crisis_resources_for_user

journal_bp = Blueprint("journal", __name__)

MAX_ENTRY_LENGTH = 5000


@journal_bp.route("/journal")
@login_required
def journal_page():
    entries = get_journal_entries(current_user()["id"], limit=30)
    onboard = request.args.get("onboard") == "1"
    return render_template("journal.html", entries=entries, emotion_meta=EMOTION_META,
                           onboard=onboard)


@journal_bp.route("/api/journal", methods=["POST"])
@login_required
def submit_journal():
    data = request.get_json(silent=True) or request.form
    text = (data.get("entry_text") or "").strip()
    # Voice Journal (Feature 5): the browser's SpeechRecognition API does the
    # actual speech-to-text transcription client-side (journal.js) -- no raw
    # audio is ever sent to or stored on the server, which keeps this simple
    # and avoids a new sensitive-data (voice biometric) storage surface for
    # a mental-health app. All we get here is a tag for how the text
    # originated, purely for adoption analytics.
    input_method = (data.get("input_method") or "text").strip()
    if input_method not in ("text", "voice", "voice_edited"):
        input_method = "text"

    if not text:
        return jsonify({"ok": False, "error": "Journal entry can't be empty."}), 400
    if len(text) > MAX_ENTRY_LENGTH:
        return jsonify({"ok": False, "error": f"Entries are capped at {MAX_ENTRY_LENGTH} characters."}), 400

    analysis = analyze_journal_entry(text)
    entry = save_journal_entry(current_user()["id"], text, analysis, input_method=input_method)
    # Derived purely from stored fields (confidence + low_confidence), so
    # this works identically for entries saved before this wording existed
    # -- no backfill/migration needed. See confidence_label()'s docstring
    # for why this replaces a raw percentage in the UI.
    entry["confidence_label"] = confidence_label(entry["confidence"], entry.get("low_confidence", False))

    # Feed this entry into long-term memory (extraction + upsert + periodic
    # maintenance). Runs on every entry but is cheap: most of the cost is
    # one Gemini extraction call, same pattern as emotion analysis above.
    update_memory_from_entry(current_user()["id"], text)

    response = {
        "ok": True,
        "entry": entry,
        "meta": EMOTION_META[entry["emotion_label"]],
        "explanation": generate_emotion_explanation(text, analysis),
    }
    if analysis["crisis_flag"]:
        response["crisis"] = {
            "message": (
                "What you wrote sounds really heavy, and I want you to know "
                "support is available right now. You don't have to go through "
                "this alone — please consider reaching out to one of the "
                "resources below, or to someone you trust."
            ),
            "resources": crisis_resources_for_user(current_user()),
        }
    else:
        response["recommendations"] = get_recommendations(None, journal_emotion=entry["emotion_label"])
        response["memory_insight"] = generate_pattern_insight(current_user()["id"])["insight"]

    return jsonify(response)
