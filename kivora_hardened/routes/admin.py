from flask import Blueprint, jsonify, render_template, request

from auth_utils import admin_required
from database.db import (
    approve_testimonial, create_coupon, get_admin_stats, list_all_users,
    list_coupons, list_feedback, list_testimonials, set_user_admin, set_user_plan,
)
from ml.churn import compute_churn_risk

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin")
@admin_required
def admin_dashboard():
    stats = get_admin_stats()
    users = list_all_users()
    for u in users:
        u["churn"] = compute_churn_risk(u["id"])
    return render_template(
        "admin.html", stats=stats, users=users,
        coupons=list_coupons(), feedback=list_feedback(),
        pending_testimonials=list_testimonials(approved_only=False),
    )


@admin_bp.route("/api/admin/users/<int:user_id>/plan", methods=["POST"])
@admin_required
def admin_set_plan(user_id):
    plan = (request.get_json(silent=True) or {}).get("plan")
    if plan not in ("free", "premium"):
        return jsonify({"ok": False, "error": "Plan must be 'free' or 'premium'."}), 400
    set_user_plan(user_id, plan)
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/users/<int:user_id>/admin", methods=["POST"])
@admin_required
def admin_set_admin(user_id):
    is_admin = bool((request.get_json(silent=True) or {}).get("is_admin"))
    set_user_admin(user_id, is_admin)
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/coupons", methods=["POST"])
@admin_required
def admin_create_coupon():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    discount = data.get("discount_percent")
    max_uses = data.get("max_uses", 1)
    if not code or not isinstance(discount, int) or not (0 < discount <= 100):
        return jsonify({"ok": False, "error": "Provide a code and a discount_percent 1-100."}), 400
    create_coupon(code, discount, max_uses=max_uses)
    return jsonify({"ok": True, "coupons": list_coupons()})


@admin_bp.route("/api/admin/testimonials/<int:testimonial_id>/approve", methods=["POST"])
@admin_required
def admin_approve_testimonial(testimonial_id):
    approve_testimonial(testimonial_id, approved=True)
    return jsonify({"ok": True})
