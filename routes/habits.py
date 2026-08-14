from flask import Blueprint, jsonify, render_template, request

from auth_utils import current_user, login_required
from database.db import checkin_habit, create_habit, get_habit_status

habits_bp = Blueprint("habits", __name__)

MAX_HABIT_NAME_LENGTH = 60
MAX_HABITS_PER_USER = 15


@habits_bp.route("/habits")
@login_required
def habits_page():
    return render_template("habits.html")


@habits_bp.route("/api/habits", methods=["GET", "POST"])
@login_required
def habits_api():
    user_id = current_user()["id"]
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "Habit name can't be empty."}), 400
        if len(name) > MAX_HABIT_NAME_LENGTH:
            return jsonify({"ok": False, "error": "Habit name is too long."}), 400
        if len(get_habit_status(user_id)) >= MAX_HABITS_PER_USER:
            return jsonify({"ok": False, "error": f"Limit of {MAX_HABITS_PER_USER} habits reached."}), 400
        create_habit(user_id, name)

    return jsonify({"ok": True, "habits": get_habit_status(user_id)})


@habits_bp.route("/api/habits/<int:habit_id>/checkin", methods=["POST"])
@login_required
def checkin(habit_id):
    user_id = current_user()["id"]
    result = checkin_habit(habit_id, user_id)
    if result is None:
        return jsonify({"ok": False, "error": "Habit not found."}), 404
    return jsonify({"ok": True, "habits": get_habit_status(user_id)})
