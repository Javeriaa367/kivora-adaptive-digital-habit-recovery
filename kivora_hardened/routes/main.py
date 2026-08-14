import os

from flask import Blueprint, jsonify, redirect, render_template, request, send_file, url_for

from auth_utils import current_user, login_required
from database.db import get_dashboard_data, get_onboarding_state, get_recent_predictions
from ml.gamification import compute_badges, get_daily_challenge
from ml.coach import get_daily_coach
from ml.mailer import send_weekly_report_email
from ml.predictor import load_metadata
from ml.weekly_report import build_weekly_report_pdf

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Public landing page. Logged-in users skip straight to the app."""
    if current_user():
        return redirect(url_for("main.dashboard"))
    return render_template("landing.html")


@main_bp.route("/onboarding")
@login_required
def onboarding():
    """Guided first-run flow: check-in -> results -> first journal entry.
    Once both are done the dashboard becomes the home page again."""
    state = get_onboarding_state(current_user()["id"])
    if state["completed"]:
        return redirect(url_for("main.dashboard"))
    return render_template("onboarding.html", onboard_state=state)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    state = get_onboarding_state(current_user()["id"])
    if not state["started"]:
        # A brand-new account lands on the guided onboarding flow instead of
        # the empty dashboard shell.
        return redirect(url_for("main.onboarding"))
    metadata = load_metadata()
    recent = get_recent_predictions(current_user()["id"], limit=5)
    latest = recent[0] if recent else None
    return render_template("dashboard.html", metadata=metadata, recent=recent, latest=latest,
                            daily_coach=get_daily_coach())


@main_bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@main_bp.route("/checkin")
@login_required
def checkin():
    metadata = load_metadata()
    onboard = request.args.get("onboard") == "1"
    return render_template("checkin.html", metadata=metadata,
                            daily_coach=get_daily_coach(), onboard=onboard)


@main_bp.route("/api/dashboard-data")
@login_required
def dashboard_data():
    data = get_dashboard_data(current_user()["id"], days=90)
    data["badges"] = compute_badges(data)
    data["daily_challenge"] = get_daily_challenge()
    return jsonify(data)


@main_bp.route("/tips")
@login_required
def tips():
    return render_template("tips.html")


@main_bp.route("/insights")
@login_required
def insights():
    metadata = load_metadata()
    return render_template("insights.html", metadata=metadata)


@main_bp.route("/games")
@login_required
def games():
    return render_template("games.html")


@main_bp.route("/focus")
@login_required
def focus_timer():
    return render_template("focus.html")


@main_bp.route("/reports/weekly.pdf")
@login_required
def weekly_report_pdf():
    import io
    pdf_bytes = build_weekly_report_pdf(current_user())
    return send_file(
        io.BytesIO(pdf_bytes), mimetype="application/pdf",
        as_attachment=True, download_name="kivora-weekly-report.pdf",
    )


@main_bp.route("/reports/email", methods=["POST"])
@login_required
def weekly_report_email():
    """Email the logged-in user a plain-language weekly summary (real SMTP
    when configured, console print in dev). Callable manually from the
    dashboard and safe to drive from a scheduled job."""
    sent = send_weekly_report_email(current_user())
    return jsonify({"ok": True, "sent": sent, "mode": "smtp" if os.environ.get("SMTP_HOST") else "dev"})
