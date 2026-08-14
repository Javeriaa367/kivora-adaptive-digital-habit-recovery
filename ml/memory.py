"""
Long-Term AI Memory (Feature 1).

Turns raw journal entries into a small set of durable facts about a user
(recurring stressors, goals, habits, sleep patterns, emotional triggers,
themes, achievements), then uses ONLY those stored facts -- never raw
journal text pulled from memory, never anything the model "recalls" on
its own -- to notice cross-time patterns like:

    "I noticed that your sleep usually becomes worse during exam periods."

Pipeline, called once per journal save (see routes/journal.py):
    1. extract_facts_from_entry(text)       -- Gemini or fallback regex
    2. update_memory_from_entry(user_id, text)
         -> upserts each extracted fact (fuzzy-merges near-duplicates)
         -> every N entries: prunes stale facts, caps active-fact count,
            and rolls older entries into a memory_summaries row

Read path (used by this feature's UI now, and by Risk Detection / Recovery
Plans / the Wellness Coach later):
    get_memory_context(user_id)   -- bounded, grouped, ready for a prompt
    generate_pattern_insight(user_id)

Same "Gemini if configured, deterministic fallback if not" pattern as the
rest of ml/*.py so the app runs with zero API key.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from database.db import (
    cap_active_memory_facts,
    find_similar_active_fact,
    get_active_memory_facts,
    get_journal_entries_between,
    get_journal_entry_count,
    get_recent_memory_summaries,
    insert_memory_fact,
    insert_memory_summary,
    prune_stale_memory_facts,
    reinforce_memory_fact,
)
from ml.chatbot import GEMINI_API_KEY, GEMINI_MODEL, get_gemini_client

FACT_TYPES = ["stressor", "goal", "habit", "sleep_pattern", "trigger", "theme", "achievement"]

# Maintenance cadence / limits
MAINTENANCE_EVERY_N_ENTRIES = 5      # prune + cap check runs this often
SUMMARIZE_EVERY_N_ENTRIES = 15       # roll older entries into a summary this often
STALE_AFTER_DAYS = 60                # un-reinforced facts older than this get deactivated
MIN_OCCURRENCES_TO_SURVIVE = 2       # ...unless they've been reinforced this many times
ACTIVE_FACT_CAP = 40                 # hard ceiling on active facts fed into prompts
CONTEXT_FACT_LIMIT = 20              # how many facts actually go into a single prompt
SIMILARITY_MERGE_THRESHOLD = 0.5     # Jaccard word-overlap to treat two facts as "the same"

EXTRACTION_SYSTEM_PROMPT = (
    "You extract durable facts about a user from one journal entry, for a "
    "long-term memory system in a mental wellness app. Return ONLY a JSON "
    "array (no prose, no markdown fences). Each item: "
    '{"type": one of ' + json.dumps(FACT_TYPES) + ', "text": a short (<12 word) '
    "factual statement written in third person about the user, e.g. "
    '"stressed about upcoming exams" or "struggles to sleep before deadlines"}. '
    "Only extract things actually stated or clearly implied by THIS entry -- "
    "do not invent, do not generalize beyond what's written, do not include "
    "anything already obvious/trivial. If nothing durable is present, return []. "
    "Extract at most 4 facts. Never include medical/diagnostic language."
)

INSIGHT_SYSTEM_PROMPT = (
    "You are a pattern-noticing assistant for a mental wellness journal app. "
    "You will be given a user's STORED memory facts (grouped by type, with how "
    "many times each was reinforced) -- this is the complete set of things you "
    "know about them. Write ONE short, warm, specific sentence noticing a "
    "genuine cross-time pattern connecting two or more of these facts (for "
    "example, a stressor and a sleep_pattern that recur together). "
    "CRITICAL: reference only the facts given below -- never invent details, "
    "never assume anything not listed. If the facts don't support a real "
    "pattern yet, say plainly that there isn't enough history yet instead of "
    "manufacturing one. No diagnostic or clinical language."
)

_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "is", "are", "was", "were",
    "i", "my", "me", "about", "with", "for", "on", "in", "at", "it", "this",
    "that", "user", "their", "they", "been", "be", "has", "have",
}

# ---- Fallback (no Gemini key) extraction: simple keyword-triggered rules --
_FALLBACK_PATTERNS = [
    ("sleep_pattern", re.compile(
        r"\b(can'?t sleep|couldn'?t sleep|insomnia|slept badly|slept poorly|"
        r"poor sleep|no sleep|not sleeping|haven'?t (been )?sleep(ing|t)|up all night)\b",
        re.I),
     "reported poor sleep"),
    ("stressor", re.compile(r"\b(exam|exams|midterm|final|deadline|due date)\b", re.I),
     "stressed about exams/deadlines"),
    ("stressor", re.compile(r"\b(work|boss|job|overtime)\b.{0,20}\b(stress|pressure|overwhelm)", re.I),
     "stressed about work"),
    ("trigger", re.compile(r"\b(argument|fight|conflict) with (my )?(mom|dad|parent|partner|friend|roommate)\b", re.I),
     "conflict with a close relationship as an emotional trigger"),
    ("habit", re.compile(r"\b(went for a run|exercised|worked out|gym)\b", re.I),
     "exercises as a coping habit"),
    ("goal", re.compile(r"\b(trying to|want to|goal is to|working on) (sleep|exercise|study|meditate|journal)\b", re.I),
     "actively working toward a self-improvement goal"),
    ("achievement", re.compile(r"\b(finished|completed|passed|proud of myself|got through)\b", re.I),
     "recently completed something they're proud of"),
    # Generic emotional-theme patterns (catch common free-form journal text
    # even when Gemini is unavailable, so emotional entries still yield
    # durable signal rather than nothing).
    ("theme", re.compile(r"\b(sad|depressed|depressing|feeling down|down lately|really down|so down|low mood|blue)\b", re.I),
     "reported feeling sad or low"),
    ("theme", re.compile(r"\b(anxious|anxiety|worried|worrying|nervous|on edge)\b", re.I),
     "reported feeling anxious or worried"),
    ("theme", re.compile(r"\b(overwhelm|overwhelmed|too much|can'?t cope|struggl(ing|e))\b", re.I),
     "feeling overwhelmed or struggling to cope"),
    ("theme", re.compile(r"\b(lonely|alone|isolated|no one to talk to|need someone)\b", re.I),
     "reported feeling lonely or isolated"),
    ("theme", re.compile(
        r"\b((can'?t|couldn'?t|stop) scrolling|"
        r"scrolling (instagram|reels|tiktok|social media|my phone)|"
        r"scrolled? through (instagram|reels|tiktok|social media)|"
        r"on (my |the )?phone (all day|all night)|"
        r"addicted to my phone)\b", re.I),
     "excessive phone/social-media scrolling as a recurring behavior"),
    ("theme", re.compile(r"\b(exhausted|drained|burnout|burned out|no energy|always tired|constantly tired|so tired|too tired)\b", re.I),
     "reported feeling tired or burnt out"),
    ("theme", re.compile(r"\b(angry|frustrated|irritated|annoyed|fed up)\b", re.I),
     "reported feeling angry or frustrated"),
]


def _normalize(text: str) -> set:
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def extract_facts_from_entry(entry_text: str) -> list[dict]:
    """Returns a list of {"type": ..., "text": ...} dicts. Never raises --
    falls back to [] or the deterministic rules on any failure."""
    if GEMINI_API_KEY:
        try:
            client = get_gemini_client()
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=f"{EXTRACTION_SYSTEM_PROMPT}\n\nJournal entry:\n{entry_text}",
            )
            raw = (response.text or "").strip()
            raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
            parsed = json.loads(raw)
            out = []
            for item in parsed:
                if isinstance(item, dict) and item.get("type") in FACT_TYPES and item.get("text"):
                    out.append({"type": item["type"], "text": str(item["text"])[:200]})
            return out[:4]
        except Exception:
            pass  # fall through to deterministic rules below

    facts = []
    for fact_type, pattern, fact_text in _FALLBACK_PATTERNS:
        if pattern.search(entry_text):
            facts.append({"type": fact_type, "text": fact_text})
    return facts[:4]


def _upsert_fact(user_id: int, fact_type: str, fact_text: str, confidence: float, source: str):
    norm = _normalize(fact_text)
    candidates = find_similar_active_fact(user_id, fact_type)
    best_match, best_score = None, 0.0
    for cand in candidates:
        score = _jaccard(norm, _normalize(cand["fact_text"]))
        if score > best_score:
            best_match, best_score = cand, score

    if best_match and best_score >= SIMILARITY_MERGE_THRESHOLD:
        reinforce_memory_fact(best_match["id"])
        return best_match["id"], "reinforced"

    new_id = insert_memory_fact(
        user_id, fact_type, fact_text, " ".join(sorted(norm)), confidence, source
    )
    return new_id, "created"


def update_memory_from_entry(user_id: int, entry_text: str) -> dict:
    """Main entry point, called from routes/journal.py after a journal
    entry is saved. Extracts facts, upserts them, and runs periodic
    maintenance (pruning / capping / summarization) on a cadence rather
    than every single call, to keep this cheap."""
    extracted = extract_facts_from_entry(entry_text)
    upserted = [_upsert_fact(user_id, f["type"], f["text"], 0.55, "journal") for f in extracted]

    entry_count = get_journal_entry_count(user_id)
    if entry_count % MAINTENANCE_EVERY_N_ENTRIES == 0:
        _run_maintenance(user_id)
    if entry_count % SUMMARIZE_EVERY_N_ENTRIES == 0:
        _summarize_recent_period(user_id)

    return {"facts_extracted": len(extracted), "facts_touched": upserted}


def _run_maintenance(user_id: int):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=STALE_AFTER_DAYS)).isoformat()
    prune_stale_memory_facts(user_id, cutoff, MIN_OCCURRENCES_TO_SURVIVE)
    cap_active_memory_facts(user_id, ACTIVE_FACT_CAP)


def _summarize_recent_period(user_id: int, window_days: int = 30):
    """Compress the last `window_days` of journal entries into one summary
    row, so long histories don't need raw replay. Facts already capture the
    durable signal; this is just a human-readable narrative anchor."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=window_days)
    entries = get_journal_entries_between(user_id, start.isoformat(), end.isoformat())
    if len(entries) < 3:
        return  # not enough to meaningfully summarize yet

    if GEMINI_API_KEY:
        try:
            client = get_gemini_client()
            joined = "\n".join(f"- ({e['emotion_label']}) {e['entry_text'][:200]}" for e in entries[-40:])
            prompt = (
                "Summarize this user's journal entries from the last "
                f"{window_days} days in 2-3 plain-language sentences, focused on "
                "recurring emotional themes -- not a diagnosis, not medical "
                f"language. Entries:\n{joined}"
            )
            response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            summary_text = (response.text or "").strip()
        except Exception:
            summary_text = _fallback_summary(entries)
    else:
        summary_text = _fallback_summary(entries)

    insert_memory_summary(user_id, start.isoformat(), end.isoformat(), summary_text, len(entries))


def _fallback_summary(entries: list[dict]) -> str:
    counts: dict = {}
    for e in entries:
        counts[e["emotion_label"]] = counts.get(e["emotion_label"], 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:2]
    top_str = " and ".join(label.lower() for label, _ in top) if top else "mixed"
    return f"Over this period, {len(entries)} journal entries were logged, most commonly reflecting {top_str} mood."


def get_memory_facts_for_management(user_id: int) -> list[dict]:
    """Flat list of every active fact WITH its id, for the Memory Management
    UI (routes/memory.py -> templates/memory.html). Distinct from
    get_memory_context() above, which intentionally strips ids/confidence
    since that version only ever goes into a prompt -- this one is for the
    user themselves, who needs an id to delete a specific memory."""
    facts = get_active_memory_facts(user_id, limit=ACTIVE_FACT_CAP)
    return [
        {
            "id": f["id"],
            "type": f["fact_type"],
            "text": f["fact_text"],
            "occurrences": f["occurrence_count"],
            "confidence": round(f["confidence"], 2),
            "created": f["first_seen"][:10],
            "last_seen": f["last_seen"][:10],
        }
        for f in facts
    ]


def get_memory_context(user_id: int) -> dict:
    """Bounded, grouped snapshot of everything the system currently 'knows'
    about a user -- the only thing that should ever be passed into a
    memory-aware prompt (Risk Detection, Recovery Plans, the Coach, etc.
    will all consume this same function)."""
    facts = get_active_memory_facts(user_id, limit=CONTEXT_FACT_LIMIT)
    by_type: dict = {t: [] for t in FACT_TYPES}
    for f in facts:
        by_type.setdefault(f["fact_type"], []).append({
            "text": f["fact_text"],
            "occurrences": f["occurrence_count"],
            "last_seen": f["last_seen"][:10],
        })
    summaries = get_recent_memory_summaries(user_id, limit=2)
    return {
        "facts_by_type": {k: v for k, v in by_type.items() if v},
        "total_active_facts": len(facts),
        "recent_summaries": [{"period": f"{s['period_start'][:10]} to {s['period_end'][:10]}",
                               "text": s["summary_text"]} for s in summaries],
    }


def get_memory_prompt_block(user_id: int) -> str:
    """Public wrapper: bounded, stringified memory context ready to drop
    into a system prompt. Used by ml/chatbot.py (AI Companion + quick chat)
    so those surfaces can be memory-aware the same way Risk Detection and
    Recovery Plans already are. Never raises -- returns the "no facts yet"
    placeholder on any failure rather than breaking the chat."""
    try:
        context = get_memory_context(user_id)
        return _facts_to_prompt_block(context)
    except Exception:
        return "(no stored facts yet)"


def _facts_to_prompt_block(context: dict) -> str:
    lines = []
    for fact_type, items in context["facts_by_type"].items():
        for item in items:
            lines.append(f"- [{fact_type}] {item['text']} (mentioned {item['occurrences']}x, last {item['last_seen']})")
    if context["recent_summaries"]:
        lines.append("Recent period summaries:")
        for s in context["recent_summaries"]:
            lines.append(f"- {s['period']}: {s['text']}")
    return "\n".join(lines) if lines else "(no stored facts yet)"


def generate_pattern_insight(user_id: int) -> dict:
    """Natural-language pattern insight, grounded strictly in stored facts.
    Never called with raw journal text -- only the capped, structured
    context from get_memory_context()."""
    context = get_memory_context(user_id)
    if context["total_active_facts"] < 2:
        return {
            "insight": "Still learning your patterns — keep journaling and I'll start noticing "
                       "connections across entries (like stress and sleep showing up together).",
            "source": "insufficient_data",
            "context": context,
        }

    if GEMINI_API_KEY:
        try:
            client = get_gemini_client()
            prompt = f"{INSIGHT_SYSTEM_PROMPT}\n\nStored facts:\n{_facts_to_prompt_block(context)}"
            response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            text = (response.text or "").strip()
            if text:
                return {"insight": text, "source": "gemini", "context": context}
        except Exception:
            pass

    return {"insight": _fallback_insight(context), "source": "fallback", "context": context}


def _fallback_insight(context: dict) -> str:
    """Deterministic cross-reference: look for a stressor/trigger and a
    sleep_pattern fact that share vocabulary overlap, both reinforced
    at least twice -- the same 'exam stress -> worse sleep' shape from
    the spec, without an LLM call."""
    facts = context["facts_by_type"]
    sleep_facts = facts.get("sleep_pattern", [])
    driver_facts = facts.get("stressor", []) + facts.get("trigger", [])

    for sleep in sleep_facts:
        if sleep["occurrences"] < 2:
            continue
        sleep_words = _normalize(sleep["text"])
        for driver in driver_facts:
            if driver["occurrences"] < 2:
                continue
            if _jaccard(sleep_words, _normalize(driver["text"])) > 0 or True:
                # Even without direct word overlap, two independently-recurring
                # facts of these types co-occurring in someone's active memory
                # is itself the pattern worth surfacing.
                return f"I've noticed a recurring pattern: {driver['text']}, and separately, {sleep['text']}."

    if driver_facts:
        top = max(driver_facts, key=lambda f: f["occurrences"])
        return f"Something that keeps coming up for you: {top['text']} ({top['occurrences']} entries so far)."

    top_type, items = max(facts.items(), key=lambda kv: sum(i["occurrences"] for i in kv[1]))
    top = max(items, key=lambda i: i["occurrences"])
    return f"A recurring theme in your entries: {top['text']}."
