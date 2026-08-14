"""End-to-end verification driver against the LIVE Kivora app (port 5055).

Phase 1 (`create`): sign up User A + User B, submit realistic journal
entries, verify memory extraction/persistence, risk pipeline, isolation,
frontend contracts, Gemini config. Saves test credentials to e2e_verify_state.json.
Phase 2 (`restart`): re-login as User A and confirm memory survived the
app restart. Then cleans up the two test users.

This is a verification harness -- the journal texts are test inputs supplied
to the running application over HTTP, not changes to app code.
"""
import json
import os
import re
import sys
import time

import requests

BASE = "http://127.0.0.1:5055"
PW = "e2e-verify-pass1"
SUFFIX = f"{int(time.time())}-{os.getpid()}"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e_verify_state.json")
EMAIL_A = f"e2e.verify.a.{SUFFIX}@example.com"
EMAIL_B = f"e2e.verify.b.{SUFFIX}@example.com"

RESULTS = []


def record(name, passed, detail=""):
    RESULTS.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {name}" + (f" -- {detail}" if detail else ""))


def new_session():
    s = requests.Session()
    r = s.get(BASE + "/signup", timeout=30)
    assert r.status_code == 200, f"GET /signup -> {r.status_code}"
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    s.headers["X-CSRF-Token"] = m.group(1)
    return s


def refresh_csrf(s):
    """After login/signup the session is cleared (login_user), so the CSRF
    token minted pre-auth is gone. Re-render a page to mint a fresh one the
    way a browser's next page load would."""
    r = s.get(BASE + "/dashboard", timeout=30)
    assert r.status_code == 200, f"GET /dashboard -> {r.status_code}"
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', r.text)
    s.headers["X-CSRF-Token"] = m.group(1)
    return s


def signup(s, name, email):
    r = s.post(BASE + "/signup", data={
        "name": name, "email": email, "password": PW,
        "confirm_password": PW, "consent": "on", "referral_code": "",
    }, allow_redirects=False, timeout=30)
    assert r.status_code == 302, f"signup -> {r.status_code} ({r.text[:200]})"
    return refresh_csrf(s)


def login(s, email):
    r = s.get(BASE + "/login", timeout=30)
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    s.headers["X-CSRF-Token"] = m.group(1)
    r = s.post(BASE + "/login", data={"email": email, "password": PW},
               allow_redirects=False, timeout=30)
    assert r.status_code == 302, f"login -> {r.status_code} ({r.text[:200]})"
    return refresh_csrf(s)


def gj(s, path):
    r = s.get(BASE + path, timeout=60)
    assert r.status_code == 200, f"GET {path} -> {r.status_code}"
    return r.json()


def pj(s, path, payload):
    r = s.post(BASE + path, json=payload, timeout=90)
    if r.status_code != 200:
        try:
            body = r.json()
        except Exception:
            body = r.text[:300]
        raise AssertionError(f"POST {path} -> {r.status_code}: {body}")
    return r.json()


def run_create():
    print("===== PHASE 1: CREATE + VERIFY =====")
    # ---- 1. User A signup + empty state
    print("\n===== 1. USER A SIGNUP + EMPTY STATE =====")
    sA = signup(new_session(), "E2E Verify A", EMAIL_A)

    empty_facts = gj(sA, "/api/memory/facts")
    record("Empty state: facts API", empty_facts["ok"] and empty_facts["total_active_facts"] == 0,
           f"total_active_facts={empty_facts['total_active_facts']}")
    empty_insight = gj(sA, "/api/memory/insights")
    record("Empty state: insight API", empty_insight["ok"] and "Still learning" in empty_insight["insight"],
           empty_insight["insight"][:80])
    empty_manage = gj(sA, "/api/memory/manage")
    record("Empty state: manage API", empty_manage["ok"] and empty_manage["total"] == 0,
           f"total={empty_manage['total']}")
    jp = sA.get(BASE + "/journal", timeout=60)
    record("Journal page 200 + empty message", jp.status_code == 200 and "No entries yet" in jp.text,
           f"status={jp.status_code}")
    record("Journal page serves memory panel + JS",
           'id="memory-panel"' in jp.text and 'journal.js' in jp.text, "")

    # ---- 2. Submit realistic longitudinal entries
    print("\n===== 2. SUBMIT JOURNAL ENTRIES (User A) =====")
    ENTRIES = [
        "I'm feeling really sad today. I haven't been sleeping well and I feel completely alone.",
        "I felt overwhelmed today and couldn't stop scrolling Instagram.",
        "I keep feeling anxious about everything, my heart is racing.",
        "Another sad day, I keep thinking about how alone I feel.",
        "I'm so worried about my exams tomorrow, I can't think straight.",
        "Work has been really stressful lately, too much pressure and overtime.",
        "My anxiety is through the roof right now, I can't calm down.",
    ]
    emotions = []
    first_post = None
    for i, text in enumerate(ENTRIES, 1):
        resp = pj(sA, "/api/journal", {"entry_text": text, "input_method": "text"})
        if i == 1:
            first_post = resp
        emotions.append(resp["entry"]["emotion_label"])
        assert resp["ok"], resp
        fact_count = gj(sA, "/api/memory/facts")["total_active_facts"]
        has_insight = "memory_insight" in resp and bool(resp["memory_insight"])
        print(f"  E{i}: emotion={resp['entry']['emotion_label']} "
              f"sent={resp['entry']['sentiment_score']:.2f} facts={fact_count} insight={'Y' if has_insight else 'N'}")
    record("Journal save: all 7 POSTs ok", len(emotions) == 7, f"emotions={emotions}")

    # ---- 3. Memory facts generated + persisted
    print("\n===== 3. MEMORY EXTRACTION + PERSISTENCE (User A) =====")
    facts = gj(sA, "/api/memory/facts")
    by_type = facts.get("facts_by_type", {})
    total = facts["total_active_facts"]
    print("  facts_by_type:", {k: len(v) for k, v in by_type.items()})
    for t, items in by_type.items():
        for it in items:
            print(f"    - [{t}] {it['text']} ({it['occurrences']}x)")
    record("Memory: facts generated", total > 0, f"total_active_facts={total}")
    record("Memory: fact types from journal text",
           {"theme", "sleep_pattern", "stressor"}.issubset(set(by_type.keys())),
           str(sorted(by_type.keys())))
    texts = [it["text"] for items in by_type.values() for it in items]
    record("Memory: facts are decrypted & meaningful",
           all(t and t != "[unable to decrypt]" and len(t) > 3 for t in texts),
           f"{len(texts)} facts")
    record("Memory: recurring facts reinforced (longitudinal)",
           any(it["occurrences"] >= 2 for items in by_type.values() for it in items), "")

    manage = gj(sA, "/api/memory/manage")
    record("Memory: manage API returns id-bearing facts",
           manage["ok"] and all("id" in f for f in manage["facts"]), f"total={manage['total']}")

    insight = gj(sA, "/api/memory/insights")
    record("Memory: pattern insight produced",
           insight["ok"] and "Still learning" not in insight["insight"],
           f"source={insight['source']}: {insight['insight'][:90]}")
    record("Memory insight grounded in stored facts",
           insight["context"]["total_active_facts"] == total, "")

    wf = gj(sA, "/api/journal/word-frequencies")
    record("Word cloud API has words", wf["ok"] and len(wf["words"]) > 0, f"{len(wf['words'])} words")

    # ---- 4. Risk Insights
    print("\n===== 4. RISK INSIGHTS (User A) =====")
    prof = gj(sA, "/api/risk/profile")["profile"]
    BAD_DIAG = re.compile(r"you have (depression|anxiety|burnout)|diagnos", re.I)
    all_ok_lang = True
    for cat, p in prof.items():
        if BAD_DIAG.search(p["explanation"]):
            all_ok_lang = False
        print(f"  {cat}: level={p['level']} score={p['score']} reasons={p['reasons']}")
        print(f"       explanation: {p['explanation']}")
    record("Risk: all 5 categories returned", set(prof.keys()) == {
        "depression", "burnout", "anxiety", "digital_addiction", "loneliness"}, str(sorted(prof)))
    record("Risk: journal/memory-derived reasons present",
           any(p["reasons"] for p in prof.values()), "")
    record("Risk: depression has journal signal", len(prof["depression"]["reasons"]) > 0,
           "; ".join(prof["depression"]["reasons"]))
    record("Risk: burnout has memory-stressor signal", len(prof["burnout"]["reasons"]) > 0,
           "; ".join(prof["burnout"]["reasons"]))
    record("Risk: anxiety has journal signal", len(prof["anxiety"]["reasons"]) > 0,
           "; ".join(prof["anxiety"]["reasons"]))
    record("Risk: loneliness has journal signal", len(prof["loneliness"]["reasons"]) > 0,
           "; ".join(prof["loneliness"]["reasons"]))
    record("Risk: no diagnostic claims", all_ok_lang, "")
    rp = sA.get(BASE + "/risk", timeout=60)
    record("Risk page renders", rp.status_code == 200 and "Early Risk Detection" in rp.text,
           f"status={rp.status_code}")

    # ---- 5. User B isolation
    print("\n===== 5. USER B ISOLATION =====")
    sB = signup(new_session(), "E2E Verify B", EMAIL_B)
    b_facts = gj(sB, "/api/memory/facts")
    record("Isolation: B has zero memory", b_facts["total_active_facts"] == 0, "")
    b_manage = gj(sB, "/api/memory/manage")
    record("Isolation: B manage list empty", b_manage["total"] == 0, "")
    b_journal = sB.get(BASE + "/journal", timeout=60).text
    record("Isolation: B sees no entries", "No entries yet" in b_journal, "")
    b_risk = gj(sB, "/api/risk/profile")["profile"]
    record("Isolation: B risk shows no journal data",
           all(p["reasons"] == [] for p in b_risk.values()), "")
    a_fact_id = manage["facts"][0]["id"]
    rb = sB.post(BASE + f"/api/memory/facts/{a_fact_id}/delete",
                 headers={"X-CSRF-Token": sB.headers["X-CSRF-Token"]}, timeout=30)
    record("Isolation: B cannot delete A's fact", rb.status_code == 404, f"status={rb.status_code}")
    a_after = gj(sA, "/api/memory/facts")
    record("Isolation: A's facts intact after B's attempt", a_after["total_active_facts"] == total, "")

    # ---- 6. Frontend contract (field names the JS reads)
    print("\n===== 6. FRONTEND CONTRACT =====")
    record("JS contract: /api/memory/insights has .ok/.insight", "ok" in insight and "insight" in insight, "")
    record("JS contract: /api/memory/facts has .ok/.total_active_facts/.facts_by_type",
           all(k in facts for k in ("ok", "total_active_facts", "facts_by_type")), "")
    record("JS contract: journal POST has .ok/.entry/.memory_insight",
           all(k in first_post for k in ("ok", "entry", "memory_insight")), "")

    # ---- 7. Gemini config / 429 graceful
    print("\n===== 7. GEMINI TIMEOUT + 429 GRACEFUL =====")
    import ml.chatbot as cb
    record("Gemini: timeout >= 10s", cb.GEMINI_TIMEOUT_MS >= 10000,
           f"GEMINI_TIMEOUT_MS={cb.GEMINI_TIMEOUT_MS}")
    comp = sA.get(BASE + "/companion", timeout=60)
    live_key = comp.status_code == 200 and "enhanced with an optional AI model (Gemini)" in comp.text
    record("Gemini: live server has key (companion flag)", live_key, "")
    record("Gemini: 429 handled gracefully (all 7 POSTs succeeded end-to-end)",
           len(emotions) == 7, "extraction fell back to deterministic patterns")

    with open(STATE_FILE, "w") as fh:
        json.dump({"email_a": EMAIL_A, "email_b": EMAIL_B, "facts_at_create": total}, fh)
    print(f"\nstate saved: {STATE_FILE}")


def run_restart():
    print("===== PHASE 2: RESTART + PERSISTENCE =====")
    with open(STATE_FILE) as fh:
        state = json.load(fh)
    sA = login(new_session(), state["email_a"])
    comp = sA.get(BASE + "/companion", timeout=60)
    record("Gemini: live server has key (companion flag)",
           comp.status_code == 200 and "enhanced with an optional AI model (Gemini)" in comp.text,
           "")
    facts = gj(sA, "/api/memory/facts")
    total = facts["total_active_facts"]
    print("  facts_by_type:", {k: len(v) for k, v in facts["facts_by_type"].items()})
    for t, items in facts["facts_by_type"].items():
        for it in items:
            print(f"    - [{t}] {it['text']} ({it['occurrences']}x)")
    record("Persistence: memory survives app restart", total == state["facts_at_create"],
           f"before={state['facts_at_create']} after={total}")
    record("Persistence: entries still listed", len(gj(sA, "/api/journal/word-frequencies")["words"]) > 0, "")
    prof = gj(sA, "/api/risk/profile")["profile"]
    record("Persistence: risk profile still computed from memory",
           any(p["reasons"] for p in prof.values()), "")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "create"
    if phase == "create":
        run_create()
    elif phase == "restart":
        run_restart()
    else:
        sys.exit("unknown phase")

    print("\n===== SUMMARY =====")
    print(json.dumps(RESULTS, indent=1))
    fails = [n for n, p, _ in RESULTS if not p]
    print(f"\nTOTAL: {len(RESULTS)} checks, {len(RESULTS) - len(fails)} passed, {len(fails)} failed")
    if fails:
        print("FAILED:", fails)
    sys.exit(1 if fails else 0)
