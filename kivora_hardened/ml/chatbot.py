"""
Wellness companion, backed by the Gemini API when configured.

Setup (never hardcode the key -- set it as an environment variable):
    pip install google-genai
    export GEMINI_API_KEY="your-key-here"        # macOS/Linux
    setx GEMINI_API_KEY "your-key-here"           # Windows (new shell after)

Model is configurable via GEMINI_MODEL (default: gemini-flash-latest --
an alias Google maintains to always point at their current stable Flash
model, so this default won't go stale again the way gemini-2.5-flash did
in mid-2026 when it was retired for new API keys. Pin an explicit version
like gemini-3.6-flash instead if you want reproducible behavior rather
than auto-updates).

If GEMINI_API_KEY isn't set, the companion runs on deterministic
rule-based replies, so the app is fully functional without a key. Gemini
is an optional enhancement, never a dependency for core behavior.
"""
import os
import re

from ml.emotion_analyzer import CRISIS_PATTERNS
from ml.crisis_resources import crisis_reply_text_for_user

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# ---- Cost control (Phase 2, item 10) --------------------------------------
# A live Gemini key means real per-request billing. This is a basic,
# fail-safe cap: once a user hits GEMINI_DAILY_REQUEST_CAP *live* calls in a
# day, they transparently fall back to the deterministic rule-based replies
# for the rest of that day instead of the request going through -- the app
# never just starts erroring or silently eating cost. Each live call is also
# already capped at max_output_tokens=300-400 (see calls below), so a
# request cap approximates a token/cost cap without needing a token-counting
# dependency.
#
# In-process dict, same tradeoff as the companion's per-minute rate limiter
# above it: fine for a single-worker deployment, resets on restart, and
# isn't shared across multiple gunicorn workers. Swap for a DB-backed or
# Redis counter before running >1 worker in production with a live key.
GEMINI_DAILY_REQUEST_CAP = int(os.environ.get("GEMINI_DAILY_REQUEST_CAP", "30"))
_daily_usage: dict[tuple[int, str], int] = {}


def _today_key() -> str:
    import datetime
    return datetime.date.today().isoformat()


def _daily_cap_reached(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return _daily_usage.get((user_id, _today_key()), 0) >= GEMINI_DAILY_REQUEST_CAP


def _record_live_call(user_id: int | None) -> None:
    if user_id is None:
        return
    key = (user_id, _today_key())
    _daily_usage[key] = _daily_usage.get(key, 0) + 1

# Startup diagnostic -- prints once, when this module is first imported (i.e.
# when the Flask app boots), so it's obvious in the server console whether
# THIS running process actually sees a key, without digging through separate
# terminal tests that can drift out of sync with what's really running.
# Only the last 4 characters print -- never the full key -- so this is safe
# to leave in and even safe to screenshot.
if GEMINI_API_KEY:
    print(f"[chatbot] GEMINI_API_KEY loaded, ends in ...{GEMINI_API_KEY[-4:]}")
else:
    print("[chatbot] No GEMINI_API_KEY -- using deterministic rule-based responses")

SYSTEM_PROMPT = (
    "You are a supportive, non-clinical wellness assistant inside an app "
    "called Kivora. You explain the app's ML predictions in plain "
    "language, suggest general coping strategies (breathing, grounding, "
    "journaling prompts, light exercise, sleep hygiene), and keep replies "
    "short (2-4 sentences) and warm. You are NOT a therapist: never "
    "diagnose, never claim certainty about someone's mental state, and "
    "always encourage professional support for anything serious. If the "
    "user expresses self-harm or suicidal intent, do not continue "
    "normally -- express care and point them to crisis resources instead "
    "of answering the question asked."
)

# Appended when memory facts are available (see ml/memory.py). Facts are
# historical, possibly-stale signal -- never certain, never diagnostic --
# so the model is told explicitly to treat them as background, hedge any
# reference to them, and never recite the list back to the user.
MEMORY_CONTEXT_INSTRUCTIONS = (
    "\n\nYou also have some background about this specific user, learned "
    "from things they've shared before (journal entries, past chats). This "
    "is historical context, NOT guaranteed current fact and NOT a "
    "diagnosis -- people change, and a past pattern may no longer apply. "
    "Use it only to make your reply more personal and relevant, and only "
    "when it's actually relevant to what they just said. If you reference "
    "it, hedge naturally ('you've mentioned before...', 'it seems like...') "
    "-- never state it as certain, and never just list the facts back at "
    "them. If nothing here is relevant to their message, ignore it "
    "entirely.\n\nWhat you know about this user so far:\n{memory_block}"
)


def _system_prompt_with_memory(base_prompt: str, user_id: int | None) -> str:
    if not user_id:
        return base_prompt
    from ml.memory import get_memory_prompt_block  # local import: avoid a
    # circular import at module load (ml.memory imports ml.chatbot for the
    # Gemini client/config)
    block = get_memory_prompt_block(user_id)
    if not block or block == "(no stored facts yet)":
        return base_prompt
    return base_prompt + MEMORY_CONTEXT_INSTRUCTIONS.format(memory_block=block)

_client = None


def get_gemini_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# ---- Fallback stub (used when no API key is configured) -----------------
_CANNED_RESPONSES = [
    (r"\b(breath|breathing)\b", (
        "Try box breathing: inhale for 4 counts, hold for 4, exhale for 4, "
        "hold for 4. Repeat for a couple of minutes."
    )),
    (r"\b(stress|stressed|overwhelm)\b", (
        "When things feel like a lot, write down everything on your mind, "
        "then pick just the next single step."
    )),
    (r"\b(sleep|insomnia|tired)\b", (
        "A consistent wind-down routine helps a lot — same bedtime, screens "
        "off ~30 minutes before, dark cool room."
    )),
    (r"\b(sad|depress|lonely|down)\b", (
        "I'm sorry you're feeling that way. Staying connected to people you "
        "trust and getting a little movement both help — and if this "
        "sticks around, it's worth talking to a professional."
    )),
]
_FALLBACK = (
    "I'm a supportive companion, not a substitute for professional care. "
    "I can help with quick questions about your results, habits, and "
    "well-being — try asking about stress, sleep, or a breathing exercise."
)


def _stub_response(message: str) -> dict:
    lower = message.lower()
    for pattern, reply in _CANNED_RESPONSES:
        if re.search(pattern, lower):
            return {"reply": reply, "crisis": False, "stubbed": True}
    return {"reply": _FALLBACK, "crisis": False, "stubbed": True}


# ---- Main entry point ----------------------------------------------------
def get_chatbot_response(message: str, context: dict | None = None, user_id: int | None = None) -> dict:
    lower = (message or "").lower()

    # Crisis check runs BEFORE any model call, deterministically -- never
    # left to the LLM to decide whether something is a crisis.
    if any(re.search(p, lower) for p in CRISIS_PATTERNS):
        from database.db import get_user_by_id
        user = get_user_by_id(user_id) if user_id else None
        return {
            "reply": crisis_reply_text_for_user(user),
            "crisis": True,
        }

    if not GEMINI_API_KEY:
        return _stub_response(message)

    if _daily_cap_reached(user_id):
        result = _stub_response(message)
        result["daily_cap_reached"] = True
        return result

    try:
        client = get_gemini_client()
        system_instruction = _system_prompt_with_memory(SYSTEM_PROMPT, user_id)
        _record_live_call(user_id)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=message,
            config={"system_instruction": system_instruction, "max_output_tokens": 300},
        )
        text = (resp.text or "").strip()
        if not text:
            return _stub_response(message)
        return {"reply": text, "crisis": False, "stubbed": False}
    except Exception as e:
        # Never let a network/API failure crash the request -- degrade to
        # the stub and surface the failure in the flag for debugging.
        # Print server-side too: the canned reply text alone looks
        # identical to a "no key configured" state even when a key IS
        # loaded but the actual API call failed for some other reason
        # (bad model name, network block, quota, SDK/key mismatch, etc.)
        # -- this makes that distinction visible in the terminal.
        print(f"[chatbot] Gemini API call failed: {e!r}")
        return {"reply": _stub_response(message)["reply"], "crisis": False,
                "stubbed": True, "error": str(e)}


COMPANION_SYSTEM_PROMPT = SYSTEM_PROMPT + (
    " You're in a longer-form conversation now (the AI Companion page) -- "
    "you have the recent conversation history for context, so refer back "
    "to what the person already told you rather than repeating questions."
)


def get_companion_response(history: list[dict], message: str, user_id: int | None = None) -> dict:
    """Like get_chatbot_response, but with multi-turn conversation history.
    history: list of {"role": "user"|"model", "text": str}, most recent last.
    Gemini's contents format wants role "model" for assistant turns."""
    lower = (message or "").lower()
    if any(re.search(p, lower) for p in CRISIS_PATTERNS):
        from database.db import get_user_by_id
        user = get_user_by_id(user_id) if user_id else None
        return {
            "reply": crisis_reply_text_for_user(user),
            "crisis": True,
        }

    if not GEMINI_API_KEY:
        return _stub_response(message)

    if _daily_cap_reached(user_id):
        result = _stub_response(message)
        result["daily_cap_reached"] = True
        return result

    try:
        client = get_gemini_client()
        contents = [
            {"role": turn["role"], "parts": [{"text": turn["text"]}]} for turn in history
        ]
        contents.append({"role": "user", "parts": [{"text": message}]})
        system_instruction = _system_prompt_with_memory(COMPANION_SYSTEM_PROMPT, user_id)
        _record_live_call(user_id)
        resp = client.models.generate_content(
            model=GEMINI_MODEL, contents=contents,
            config={"system_instruction": system_instruction, "max_output_tokens": 400},
        )
        text = (resp.text or "").strip()
        if not text:
            return _stub_response(message)
        return {"reply": text, "crisis": False, "stubbed": False}
    except Exception as e:
        print(f"[chatbot] Gemini API call failed (companion): {e!r}")
        return {"reply": _stub_response(message)["reply"], "crisis": False,
                "stubbed": True, "error": str(e)}
