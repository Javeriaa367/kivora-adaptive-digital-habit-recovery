"""Tests for transactional email delivery (audit Phase 3 P1).

Covers both modes: the dev-mode console print (SMTP_HOST unset) and the real
SMTP path (SMTP_HOST set), exercised against a fake smtplib that records the
delivery call instead of opening a socket. Also verifies the weekly-report
email route and the HTML/plain content shape.
"""
import smtplib

import pytest

from ml import mailer


@pytest.fixture
def fake_smtp(monkeypatch):
    """Stands in for smtplib.SMTP/SMTP_SSL, recording the call and returning
    a context-manager object whose starttls/login/sendmail are captured."""
    calls = {"mode": None, "host": None, "port": None, "to": None, "msg": None,
             "starttls": False, "login": None}

    class _ServerBase:
        mode = None

        def __init__(self, host, port, *a, **k):
            calls["mode"] = self.mode
            calls["host"], calls["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            calls["starttls"] = True

        def login(self, user, password):
            calls["login"] = (user, password)

        def sendmail(self, from_email, to, msg):
            calls["to"], calls["msg"] = to, msg

    class FakeSMTP(_ServerBase):
        mode = "starttls"

    class FakeSMTP_SSL(_ServerBase):
        mode = "ssl"

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    return calls


@pytest.fixture
def smtp_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "apikey")
    monkeypatch.setenv("SMTP_PASSWORD", "s3cret")
    monkeypatch.setenv("FROM_EMAIL", "noreply@example.com")
    monkeypatch.delenv("SMTP_USE_SSL", raising=False)


def test_dev_mode_prints_and_returns_true(monkeypatch, capsys):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    ok = mailer.send_email("user@example.com", "Hi", "Hello there")
    assert ok is True
    out = capsys.readouterr().out
    assert "[DEV MODE" in out
    assert "user@example.com" in out
    assert "Hello there" in out


def test_smtp_send_uses_starttls_and_login(monkeypatch, fake_smtp, smtp_env):
    ok = mailer.send_email("user@example.com", "Hi", "Hello", "<p>Hello</p>")
    assert ok is True
    assert fake_smtp["mode"] == "starttls"
    assert fake_smtp["host"] == "smtp.example.com"
    assert fake_smtp["port"] == 587
    assert fake_smtp["starttls"] is True
    assert fake_smtp["login"] == ("apikey", "s3cret")
    assert fake_smtp["to"] == ["user@example.com"]
    assert "Hello" in fake_smtp["msg"]
    assert "text/html" in fake_smtp["msg"]


def test_smtp_implicit_tls_uses_ssl_without_starttls(monkeypatch, fake_smtp, smtp_env):
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USE_SSL", "1")
    ok = mailer.send_email("user@example.com", "Hi", "Hello")
    assert ok is True
    assert fake_smtp["mode"] == "ssl"
    assert fake_smtp["port"] == 465
    assert fake_smtp["starttls"] is False


def test_smtp_failure_returns_false(monkeypatch, smtp_env):
    class Boom:
        def __init__(self, *a, **k):
            raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", Boom)
    assert mailer.send_email("user@example.com", "Hi", "Hello") is False


def test_password_reset_email_has_html_and_plain(monkeypatch, fake_smtp, smtp_env):
    ok = mailer.send_password_reset_email("user@example.com", "https://app.example.com/reset/abc")
    assert ok is True
    assert fake_smtp["to"] == ["user@example.com"]
    msg = fake_smtp["msg"]
    assert "Reset your Kivora password" in msg
    assert "Reset my password" in msg
    assert "https://app.example.com/reset/abc" in msg


def test_weekly_report_email_includes_summary(app, make_user, monkeypatch, fake_smtp, smtp_env):
    uid = make_user()
    with app.app_context():
        from database.db import get_user_by_id, save_journal_entry, save_prediction
        user = get_user_by_id(uid)
        save_journal_entry(uid, "A calm, steady day.",
                           {"emotion_label": "Calm", "confidence": 0.8,
                            "overall_sentiment": "positive", "sentiment_score": 0.6,
                            "crisis_flag": 0})
        save_prediction(uid, {"Daily_Usage_Hours": 4.0}, {
            "wellbeing_score": {"value": 7.2}})
        ok = mailer.send_weekly_report_email(user)
    assert ok is True
    msg = fake_smtp["msg"]
    assert "Your Kivora weekly report" in msg
    assert "week in review" in msg
    assert "Journal entries" in msg
    assert "/reports/weekly.pdf" in msg


def test_weekly_report_route_sends(app, client, make_user, login, monkeypatch, fake_smtp, smtp_env):
    uid = make_user()
    login(uid)
    res = client.post("/reports/email")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["sent"] is True
    assert data["mode"] == "smtp"
