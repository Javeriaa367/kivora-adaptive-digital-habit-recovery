from flask import Blueprint, jsonify, render_template, request

from auth_utils import admin_required, current_user, super_admin_required, user_role
from database.db import (
    VALID_ROLES, approve_testimonial, create_coupon, get_admin_analytics,
    get_admin_stats, get_audit_log, get_crisis_flag_log, get_database_stats,
    get_risk_flagged_users, get_system_config_summary, get_user_admin_detail,
    get_user_by_id, list_all_users, list_coupons, list_feedback,
    list_testimonials, log_audit, set_user_admin, set_user_plan, set_user_role,
    set_user_status,
)
from ml.churn import compute_churn_risk
from ml.recovery_plans import admin_plan_preview

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin/recovery/preview")
@admin_required
def recovery_preview():
    """Admin-only read-only preview of the complete active recovery plan.

    Every day -- including days that would normally be progression-locked
    -- and every task inside them is shown, but nothing is written: no
    tasks are completed, no plan/state rows change, and the adaptive
    engine is never invoked with write side effects. Non-admins are
    rejected here by admin_required (server-side) before this runs."""
    preview = admin_plan_preview(current_user()["id"])
    return render_template("recovery_admin_preview.html", preview=preview)


@admin_bp.route("/admin")
@admin_required
def admin_dashboard():
    stats = get_admin_stats()
    users = list_all_users()
    for u in users:
        u["churn"] = compute_churn_risk(u["id"])
    viewer = current_user()
    return render_template(
        "admin.html", stats=stats, users=users,
        coupons=list_coupons(), feedback=list_feedback(),
        pending_testimonials=list_testimonials(approved_only=False),
        analytics=get_admin_analytics(days=30),
        crisis_log=get_crisis_flag_log(limit=50),
        risk_users=get_risk_flagged_users(limit=50),
        db_stats=get_database_stats(),
        system_config=get_system_config_summary(),
        audit_log=get_audit_log(limit=50),
        valid_roles=VALID_ROLES,
        viewer_role=user_role(viewer),
    )


@admin_bp.route("/api/admin/users/<int:user_id>/plan", methods=["POST"])
@admin_required
def admin_set_plan(user_id):
    plan = (request.get_json(silent=True) or {}).get("plan")
    if plan not in ("free", "premium"):
        return jsonify({"ok": False, "error": "Plan must be 'free' or 'premium'."}), 400
    set_user_plan(user_id, plan)
    log_audit(current_user()["id"], "plan_change", user_id, {"plan": plan})
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/users/<int:user_id>/admin", methods=["POST"])
@admin_required
def admin_set_admin(user_id):
    is_admin = bool((request.get_json(silent=True) or {}).get("is_admin"))
    set_user_admin(user_id, is_admin)
    log_audit(current_user()["id"], "admin_toggle", user_id, {"is_admin": is_admin})
    return jsonify({"ok": True})


@admin_bp.route("/api/admin/users/<int:user_id>/role", methods=["POST"])
@super_admin_required
def admin_set_role(user_id):
    """Owner-only: change another account's RBAC role."""
    role = (request.get_json(silent=True) or {}).get("role")
    if role not in VALID_ROLES:
        return jsonify({"ok": False, "error": f"Role must be one of: {', '.join(VALID_ROLES)}."}), 400
    target = get_user_by_id(user_id)
    if target is None:
        return jsonify({"ok": False, "error": "User not found."}), 404
    set_user_role(user_id, role)
    log_audit(current_user()["id"], "role_change", user_id, {"role": role})
    return jsonify({"ok": True, "role": role})


@admin_bp.route("/api/admin/users/<int:user_id>/status", methods=["POST"])
@admin_required
def admin_set_account_status(user_id):
    """Suspend or activate an account (blocks login while suspended)."""
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("active", "suspended"):
        return jsonify({"ok": False, "error": "Status must be 'active' or 'suspended'."}), 400
    if user_id == current_user()["id"]:
        return jsonify({"ok": False, "error": "You cannot suspend your own account."}), 400
    target = get_user_by_id(user_id)
    if target is None:
        return jsonify({"ok": False, "error": "User not found."}), 404
    set_user_status(user_id, status)
    log_audit(current_user()["id"], "status_change", user_id, {"status": status})
    return jsonify({"ok": True, "status": status})


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
    log_audit(current_user()["id"], "coupon_create", None, {"code": code.upper()})
    return jsonify({"ok": True, "coupons": list_coupons()})


@admin_bp.route("/api/admin/testimonials/<int:testimonial_id>/approve", methods=["POST"])
@admin_required
def admin_approve_testimonial(testimonial_id):
    approve_testimonial(testimonial_id, approved=True)
    log_audit(current_user()["id"], "testimonial_approve", None, {"testimonial_id": testimonial_id})
    return jsonify({"ok": True})


# ---- Admin analytics / monitoring (read-only) ------------------------------

@admin_bp.route("/api/admin/analytics")
@admin_required
def admin_analytics():
    days = request.args.get("days", type=int, default=30)
    if days < 1 or days > 365:
        return jsonify({"ok": False, "error": "days must be 1-365."}), 400
    return jsonify(get_admin_analytics(days=days))


@admin_bp.route("/api/admin/users/<int:user_id>/detail")
@admin_required
def admin_user_detail(user_id):
    detail = get_user_admin_detail(user_id)
    if detail is None:
        return jsonify({"ok": False, "error": "User not found."}), 404
    return jsonify(detail)


@admin_bp.route("/api/admin/crisis")
@admin_required
def admin_crisis_log():
    limit = request.args.get("limit", type=int, default=50)
    return jsonify({"crisis_flags": get_crisis_flag_log(limit=limit)})


@admin_bp.route("/api/admin/risk")
@admin_required
def admin_risk_users():
    limit = request.args.get("limit", type=int, default=50)
    return jsonify({"risk_users": get_risk_flagged_users(limit=limit)})


@admin_bp.route("/api/admin/system")
@admin_required
def admin_system():
    return jsonify(get_system_config_summary())


@admin_bp.route("/api/admin/database")
@admin_required
def admin_database():
    return jsonify(get_database_stats())


@admin_bp.route("/api/admin/audit")
@admin_required
def admin_audit_log():
    limit = request.args.get("limit", type=int, default=50)
    return jsonify({"audit_log": get_audit_log(limit=limit)})
