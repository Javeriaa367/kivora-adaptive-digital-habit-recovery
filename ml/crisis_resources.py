"""
Region-aware crisis resources.

The audit's P1 finding: US-only phone numbers (988, 741741) were shown to
every user, regardless of where they actually were -- a wrong phone number
in a crisis is real harm. This module resolves resources from the user's
country code and, when the country is unknown, falls back to international
directory links ONLY (never a guessed phone number).

Helpline numbers below are curated from publicly documented sources. The
"never guess" rule matters more than coverage: before launch, re-verify
each number (or drop it -- an unknown/uncovered country automatically gets
the directory-only global list).
"""

# Ordered (code, label) pairs for the signup/settings dropdowns.
SUPPORTED_COUNTRIES = [
    ("pk", "Pakistan"),
    ("us", "United States"),
    ("gb", "United Kingdom"),
    ("in", "India"),
    ("ca", "Canada"),
    ("au", "Australia"),
]

COUNTRY_LABELS = dict(SUPPORTED_COUNTRIES)

# Directory links only -- safe for ANY region, no phone numbers to get wrong.
GLOBAL_RESOURCES = [
    {
        "name": "International Association for Suicide Prevention",
        "contact": "https://www.iasp.info/resources/Crisis_Centres/",
    },
    {
        "name": "Befrienders Worldwide",
        "contact": "https://www.befrienders.org/helplines",
    },
]

COUNTRY_RESOURCES = {
    "pk": [
        {"name": "Umang Pakistan (mental-health helpline)", "contact": "Call 111-456-010"},
        {"name": "Edhi Foundation (24/7 emergency)", "contact": "Call 115"},
    ],
    "us": [
        {"name": "988 Suicide & Crisis Lifeline", "contact": "Call or text 988"},
        {"name": "Crisis Text Line", "contact": "Text HOME to 741741"},
    ],
    "gb": [
        {"name": "Samaritans", "contact": "Call 116 123 (free, 24/7)"},
        {"name": "SHOUT crisis text line", "contact": "Text SHOUT to 85258"},
    ],
    "in": [
        {"name": "KIRAN (Govt. of India mental-health helpline)", "contact": "Call 1800-599-0019 (24/7)"},
        {"name": "iCall (TISS)", "contact": "Call 9152987821"},
        {"name": "AASRA", "contact": "Call 9820466726"},
    ],
    "ca": [
        {"name": "Talk Suicide Canada", "contact": "Call 1-833-456-4566 or text 45645"},
        {"name": "Crisis Text Line", "contact": "Text CONNECT to 686868"},
    ],
    "au": [
        {"name": "Lifeline", "contact": "Call 13 11 14"},
        {"name": "Beyond Blue", "contact": "Call 1300 22 4636"},
        {"name": "Kids Helpline (for young people)", "contact": "Call 1800 55 1800"},
    ],
}


def crisis_resources_for(country_code: str | None) -> list[dict]:
    """Resolve the resource list for a country code. Unknown/blank codes
    fall back to the directory-only global list -- never a wrong number."""
    if not country_code:
        return GLOBAL_RESOURCES
    return COUNTRY_RESOURCES.get(str(country_code).strip().lower(), GLOBAL_RESOURCES)


def _user_country_code(user) -> str | None:
    """Extract a normalized country code from a user row (or None). Accepts
    both dicts and sqlite3.Row (current_user() returns the latter)."""
    if not user:
        return None
    if isinstance(user, dict):
        code = user.get("country_code")
    else:
        code = user["country_code"] if "country_code" in user.keys() else None
    return str(code).strip().lower() if code else None


def crisis_resources_for_user(user: dict | None) -> list[dict]:
    """Like crisis_resources_for(), but takes a user row from current_user()."""
    return crisis_resources_for(_user_country_code(user))


def format_resources_for_chat(resources: list[dict]) -> str:
    """Bullet lines for embedding resources into a plain-text chat reply."""
    return "\n".join(f"• {r['name']} — {r['contact']}" for r in resources)


def crisis_reply_text(country_code: str | None) -> str:
    """The AI companion/chatbot's crisis reply, with localized resources
    appended so the user gets working numbers without leaving the chat."""
    resources = crisis_resources_for(country_code)
    lines = [
        "What you're describing sounds serious, and I want to make sure you "
        "get real support, not just a chat reply. Please reach out to someone "
        "you trust or one of these right now:",
        format_resources_for_chat(resources),
        "If it's an emergency, call your local emergency number immediately.",
    ]
    return "\n\n".join(lines)


def crisis_reply_text_for_user(user: dict | None) -> str:
    return crisis_reply_text(_user_country_code(user))
