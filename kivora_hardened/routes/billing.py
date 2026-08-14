"""
Subscription billing via Stripe Checkout.

Untested live in this sandbox -- no network, no Stripe keys. The pattern
below (Checkout Session + webhook confirmation) is Stripe's standard
recommended flow, but verify it end-to-end with your own test-mode keys
before going live.

Setup:
    pip install stripe
    export STRIPE_SECRET_KEY="sk_test_..."
    export STRIPE_PRICE_ID_PREMIUM="price_..."          # from Stripe Dashboard
    export STRIPE_WEBHOOK_SECRET="whsec_..."             # from `stripe listen` or Dashboard

Webhook endpoint to register in Stripe: POST /api/billing/webhook
Events to send: checkout.session.completed, customer.subscription.deleted
"""
import os

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from auth_utils import current_user, login_required
from database.db import (
    get_user_by_id, get_user_by_stripe_customer, log_subscription_event,
    redeem_coupon, set_user_plan,
)

billing_bp = Blueprint("billing", __name__)

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID_PREMIUM = os.environ.get("STRIPE_PRICE_ID_PREMIUM")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

FREE_PLAN_DAILY_PREDICTION_LIMIT = int(os.environ.get("FREE_PLAN_DAILY_PREDICTION_LIMIT", "5"))  # feature gate -- see auth_utils / api.py


@billing_bp.route("/pricing")
@login_required
def pricing():
    return render_template("pricing.html", stripe_configured=bool(STRIPE_SECRET_KEY),
                            daily_limit=FREE_PLAN_DAILY_PREDICTION_LIMIT)


@billing_bp.route("/api/billing/checkout", methods=["POST"])
@login_required
def create_checkout_session():
    user = current_user()

    if not STRIPE_SECRET_KEY:
        return jsonify({
            "ok": False,
            "error": "Payments aren't configured yet (no STRIPE_SECRET_KEY set). "
                     "See routes/billing.py for setup.",
        }), 400

    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=user["email"],
            line_items=[{"price": STRIPE_PRICE_ID_PREMIUM, "quantity": 1}],
            success_url=url_for("billing.success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for("billing.pricing", _external=True),
            metadata={"user_id": str(user["id"])},
        )
        return jsonify({"ok": True, "checkout_url": checkout_session.url})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@billing_bp.route("/billing/success")
@login_required
def success():
    return render_template("billing_success.html")


@billing_bp.route("/api/billing/webhook", methods=["POST"])
def stripe_webhook():
    """Stripe calls this -- not user-facing, no login_required. Signature
    verification is what authenticates the request instead of a session."""
    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "Webhook secret not configured"}), 400

    import stripe
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return jsonify({"ok": False, "error": "Invalid signature"}), 400

    is_new = log_subscription_event(None, event["id"], event["type"], request.data.decode("utf-8", errors="ignore"))
    if not is_new:
        return jsonify({"ok": True, "duplicate": True})  # idempotent on Stripe retries

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        user_id = session_obj.get("metadata", {}).get("user_id")
        if user_id:
            set_user_plan(
                int(user_id), "premium",
                stripe_customer_id=session_obj.get("customer"),
                stripe_subscription_id=session_obj.get("subscription"),
            )
    elif event["type"] == "customer.subscription.deleted":
        sub_obj = event["data"]["object"]
        user = get_user_by_stripe_customer(sub_obj.get("customer"))
        if user:
            set_user_plan(user["id"], "free")

    return jsonify({"ok": True})


@billing_bp.route("/api/billing/redeem-coupon", methods=["POST"])
@login_required
def redeem():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "Enter a coupon code."}), 400
    result = redeem_coupon(code, current_user()["id"])
    return jsonify(result), (200 if result["ok"] else 400)
