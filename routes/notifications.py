from flask import Blueprint, jsonify

from auth_utils import current_user, login_required
from database.db import get_unread_notifications, mark_all_notifications_read, mark_notification_read
from ml.notifications import generate_notifications_for_user

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/api/notifications")
@login_required
def list_notifications():
    user_id = current_user()["id"]
    generate_notifications_for_user(user_id)  # rule engine runs on each fetch
    return jsonify({"ok": True, "notifications": get_unread_notifications(user_id)})


@notifications_bp.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id):
    mark_notification_read(notification_id, current_user()["id"])
    return jsonify({"ok": True})


@notifications_bp.route("/api/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    mark_all_notifications_read(current_user()["id"])
    return jsonify({"ok": True})
