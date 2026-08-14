from flask import Blueprint, jsonify, render_template, request

from auth_utils import current_user, login_required
from database.db import (
    create_assignment, create_subject, delete_subject, get_assignments,
    get_subjects, toggle_assignment,
)
from ml.study_coach import generate_study_plan

student_bp = Blueprint("student", __name__)


@student_bp.route("/student")
@login_required
def student_page():
    user_id = current_user()["id"]
    return render_template(
        "student.html", subjects=get_subjects(user_id), assignments=get_assignments(user_id)
    )


@student_bp.route("/api/student/subjects", methods=["GET", "POST"])
@login_required
def subjects_api():
    user_id = current_user()["id"]
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        exam_date = (data.get("exam_date") or "").strip() or None
        if not name:
            return jsonify({"ok": False, "error": "Subject name required."}), 400
        create_subject(user_id, name, exam_date)
    return jsonify({"ok": True, "subjects": get_subjects(user_id)})


@student_bp.route("/api/student/subjects/<int:subject_id>", methods=["DELETE"])
@login_required
def delete_subject_api(subject_id):
    user_id = current_user()["id"]
    delete_subject(subject_id, user_id)
    return jsonify({"ok": True, "subjects": get_subjects(user_id)})


@student_bp.route("/api/student/assignments", methods=["GET", "POST"])
@login_required
def assignments_api():
    user_id = current_user()["id"]
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        due_date = (data.get("due_date") or "").strip() or None
        subject_id = data.get("subject_id") or None
        if not title:
            return jsonify({"ok": False, "error": "Assignment title required."}), 400
        create_assignment(user_id, subject_id, title, due_date)
    return jsonify({"ok": True, "assignments": get_assignments(user_id)})


@student_bp.route("/api/student/assignments/<int:assignment_id>/toggle", methods=["POST"])
@login_required
def toggle_assignment_api(assignment_id):
    user_id = current_user()["id"]
    result = toggle_assignment(assignment_id, user_id)
    if result is None:
        return jsonify({"ok": False, "error": "Assignment not found."}), 404
    return jsonify({"ok": True, "assignments": get_assignments(user_id)})


@student_bp.route("/api/student/study-plan", methods=["POST"])
@login_required
def study_plan_api():
    data = request.get_json(silent=True) or {}
    daily_hours = float(data.get("daily_hours", 2))
    subjects = get_subjects(current_user()["id"])
    result = generate_study_plan(subjects, daily_hours)
    return jsonify({"ok": True, **result})
