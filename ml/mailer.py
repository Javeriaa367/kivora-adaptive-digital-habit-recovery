"""
Transactional email delivery via SMTP (password reset, weekly report).

Any SMTP provider works (SendGrid, Mailgun, Brevo, Gmail app password, ...).
Configuration is read from the environment at call time so tests can
exercise both the dev and real paths without reloading the module:

    export SMTP_HOST="smtp.sendgrid.net"
    export SMTP_PORT="587"            # 587 = STARTTLS, 465 = implicit TLS
    export SMTP_USER="apikey"
    export SMTP_PASSWORD="your-smtp-password-or-api-key"
    export SMTP_USE_SSL="0"           # set to "1" when SMTP_PORT=465
    export FROM_EMAIL="noreply@yourdomain.com"

Dev mode: if SMTP_HOST isn't set, emails are printed to the console instead
of sent -- password reset and the weekly report still work end-to-end
locally with zero email setup, and every send attempt returns True so
callers behave the same either way. Sends go through real SMTP whenever a
host is configured (failures are caught and reported, never raised).
"""
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from database.db import get_dashboard_data

DEFAULT_FROM = "noreply@kivora.local"


def _smtp_config() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER"),
        "password": os.environ.get("SMTP_PASSWORD"),
        "from_email": os.environ.get("FROM_EMAIL", DEFAULT_FROM),
        "use_ssl": os.environ.get("SMTP_USE_SSL", "0") == "1",
    }


def _build_message(to_email: str, subject: str, text_body: str, html_body: str | None,
                   from_email: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    if html_body:
        msg.attach(MIMEText(html_body, "html"))
    return msg


def _send(to_email: str, msg: MIMEMultipart) -> bool:
    cfg = _smtp_config()
    if not cfg["host"]:
        print(f"\n[DEV MODE — no SMTP configured] Email to {to_email}:\nSubject: {msg['Subject']}\n{msg.get_payload()[0].get_payload()}\n")
        return True

    try:
        if cfg["use_ssl"]:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30) as server:
                if cfg["user"]:
                    server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from_email"], [to_email], msg.as_string())
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
                server.starttls()
                if cfg["user"]:
                    server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from_email"], [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False


def _html_wrap(title: str, body_html: str) -> str:
    return (
        "<div style=\"font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;"
        "color:#0B1120;line-height:1.5\">"
        f"<div style=\"background:#0B1120;color:#fff;padding:18px 24px;border-radius:12px 12px 0 0\">"
        f"<strong>Kivora</strong></div>"
        f"<div style=\"border:1px solid #E2E8F0;border-top:0;padding:24px;border-radius:0 0 12px 12px\">"
        f"<h2 style=\"margin-top:0\">{title}</h2>{body_html}"
        f"<p style=\"color:#94A3B8;font-size:12px;margin-top:28px\">You're receiving this because you "
        f"use Kivora. This is a mental-health support tool, not a substitute for "
        f"professional care.</p></div></div>"
    )


def _button(url: str, label: str) -> str:
    return (
        f'<p style="text-align:center;margin:24px 0"><a href="{url}" '
        'style="background:#0EA5A0;color:#fff;text-decoration:none;font-weight:bold;'
        'padding:12px 22px;border-radius:10px;display:inline-block">'
        f"{label}</a></p>"
    )


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    cfg = _smtp_config()
    return _send(to_email, _build_message(to_email, subject, text_body, html_body, cfg["from_email"]))


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    text_body = (
        f"Someone requested a password reset for your Kivora account.\n\n"
        f"Reset your password: {reset_url}\n\n"
        f"This link expires in 30 minutes. If you didn't request this, ignore this email."
    )
    html_body = _html_wrap(
        "Reset your password",
        f"<p>We got a request to reset your Kivora password.</p>"
        f"{_button(reset_url, 'Reset my password')}"
        f"<p style=\"font-size:13px\">This link expires in 30 minutes. If you didn't request "
        f"this, you can safely ignore this email.</p>",
    )
    return send_email(to_email, "Reset your Kivora password", text_body, html_body)


def send_weekly_report_email(user_row) -> bool:
    """Emails a plain-language summary of the user's last 7 days plus a link
    to the full PDF. Safe to call from a cron job for re-engagement nudges."""
    data = get_dashboard_data(user_row["id"], days=7)
    name = user_row["name"].split()[0] if user_row["name"] else "there"
    entries = data["total_journal_entries"]
    predictions = data["total_predictions"]
    mood = data["most_common_emotion"] or "no journal entries yet"
    streak = data["journal_streak_days"]

    text_body = (
        f"Hi {name}, here's your Kivora week in review.\n\n"
        f"- Journal entries: {entries}\n"
        f"- Assessments run: {predictions}\n"
        f"- Most common mood: {mood}\n"
        f"- Journaling streak: {streak} day(s)\n\n"
        f"Open your full report: {_weekly_pdf_url()}"
    )
    html_body = _html_wrap(
        "Your week in review",
        f"<p>Hi {name}, here's a quick look at your last 7 days.</p>"
        f"<table style=\"width:100%;border-collapse:collapse;font-size:14px\">"
        f"<tr><td style=\"padding:8px 0;color:#64748B\">Journal entries</td>"
        f"<td style=\"padding:8px 0;font-weight:bold\">{entries}</td></tr>"
        f"<tr><td style=\"padding:8px 0;color:#64748B\">Assessments run</td>"
        f"<td style=\"padding:8px 0;font-weight:bold\">{predictions}</td></tr>"
        f"<tr><td style=\"padding:8px 0;color:#64748B\">Most common mood</td>"
        f"<td style=\"padding:8px 0;font-weight:bold\">{mood}</td></tr>"
        f"<tr><td style=\"padding:8px 0;color:#64748B\">Journaling streak</td>"
        f"<td style=\"padding:8px 0;font-weight:bold\">{streak} day(s)</td></tr>"
        f"</table>"
        f"{_button(_weekly_pdf_url(), 'Open your full report (PDF)')}"
        f"<p style=\"font-size:13px\">This lands in your Dashboard too, any time.</p>",
    )
    return send_email(user_row["email"], "Your Kivora weekly report", text_body, html_body)


def _weekly_pdf_url() -> str:
    return os.environ.get("APP_BASE_URL", "http://localhost:5000") + "/reports/weekly.pdf"
