from flask import Blueprint, jsonify, render_template

from auth_utils import current_user, login_required
from database.db import clear_all_memory, delete_memory_fact
from ml.memory import generate_pattern_insight, get_memory_context, get_memory_facts_for_management

memory_bp = Blueprint("memory", __name__)


@memory_bp.route("/memory")
@login_required
def memory_page():
    """'Your AI Memory' dashboard section: what the AI has learned about
    this user, with full view/delete/clear-all control (see AI_Memory
    spec sections 10-11). Facts are fetched client-side via the JSON APIs
    below, same pattern as templates/habits.html."""
    return render_template("memory.html")


@memory_bp.route("/api/memory/insights")
@login_required
def memory_insights():
    """The pattern-recognition insight + the underlying fact context it was
    grounded in (returned too, so the UI/consumer can show its work)."""
    result = generate_pattern_insight(current_user()["id"])
    return jsonify({"ok": True, **result})


@memory_bp.route("/api/memory/facts")
@login_required
def memory_facts():
    """Raw browsable memory state -- what the AI currently 'remembers'
    about this user, grouped by type. Used for a transparency view."""
    context = get_memory_context(current_user()["id"])
    return jsonify({"ok": True, **context})


@memory_bp.route("/api/memory/manage")
@login_required
def memory_manage():
    """Flat, id-bearing fact list for the Memory Management UI, where the
    user needs an id to act on a specific memory (unlike /api/memory/facts,
    which is grouped/id-less and only meant for read-only display)."""
    user_id = current_user()["id"]
    facts = get_memory_facts_for_management(user_id)
    return jsonify({"ok": True, "facts": facts, "total": len(facts)})


@memory_bp.route("/api/memory/facts/<int:fact_id>/delete", methods=["POST"])
@login_required
def memory_delete_fact(fact_id):
    """Delete a single memory. delete_memory_fact() scopes the DELETE to
    the logged-in user_id, so a fact_id belonging to another user is
    silently a no-op (404) rather than ever being deletable cross-account."""
    deleted = delete_memory_fact(current_user()["id"], fact_id)
    if not deleted:
        return jsonify({"ok": False, "error": "Memory not found."}), 404
    return jsonify({"ok": True})


@memory_bp.route("/api/memory/clear", methods=["POST"])
@login_required
def memory_clear_all():
    """Delete every stored memory fact and summary for this user. The
    frontend is expected to confirm with the user before calling this --
    it's immediate and irreversible."""
    count = clear_all_memory(current_user()["id"])
    return jsonify({"ok": True, "deleted": count})
