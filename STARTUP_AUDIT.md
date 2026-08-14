# MindMetrics AI — Startup Readiness Audit

**Audit basis:** static reading of the actual codebase at `mindmetrics_ai_journal_correction_pass`, runtime verification (app boots; `predict_all()` returns real outputs; `pytest` = **72 passed**; live DB inspected), plus honest inference about what is and isn't shipped.

**Verification performed:**
- `python -m pytest -x -q` → 72 passed
- App boots without a `GEMINI_API_KEY`; prediction pipeline returns real model outputs
- `app.db` inspected: **1 user** (the developer), 3 journal entries, 0 predictions, 1 recovery plan, 5 risk snapshots, 0 subscriptions/coupons/testimonials — this is a demo database, not a product with users
- Confirmed `flask_wtf` is **not installed** → the `WTF_CSRF_ENABLED = False` in `tests/conftest.py:42` is a dead no-op; there is **no CSRF protection anywhere**
- Confirmed root route `/` is `@login_required` → **there is no landing page**
- Confirmed `ml_pipeline/final_train.py` is referenced by `ml/predictor.py` but does not exist → **no training pipeline or training data in the repo**

---

## Trust-floor correction pass — update (supersedes the Phase 1 items below)

This audit predates several rounds of fixes already landed in this repo (CSRF via
`security.py`, `database/persistence.py`, `routes/settings.py` deletion/export,
`ml/crisis_resources.py`, `ml_pipeline/final_train.py`, onboarding, etc.) — most of
the "Phase 1" P0 items in section 16 below were already ✅ **done** before this pass
started, not just claimed done. This pass verified each one against the actual
code/tests and closed the one gap that was still open (encryption at rest).

**Verification performed for this pass:** `python -m pytest -q` → **150 passed**
(was 72 at the original audit, 145 before this pass, +5 net from this pass's new
encryption tests; the difference between 72 and 145 is prior work not covered by
this audit revision).

| Item | Status | Evidence |
|---|---|---|
| 1. SECRET_KEY fails closed in prod | ✅ Already done, verified | `config.py:_load_secret_key()` raises `RuntimeError` when `FLASK_ENV=production`/`K_SERVICE`/`CLOUD_RUN` and `SECRET_KEY` unset; dev falls back to a random per-process key. No dedicated test existed for this; verified manually via subprocess (`FLASK_ENV=production python -c "import config"` → raises). |
| 2. Real CSRF protection | ✅ Already done, verified | `security.py` — session-token CSRF (not flask-wtf, but functionally equivalent: token in session, required on every POST/PUT/PATCH/DELETE via form field / JSON body / `X-CSRF-Token` header, `hmac.compare_digest` comparison, exempted only for the signature-authenticated Stripe webhook). Wired via `before_request` in `app.py`. `tests/test_privacy_csrf_landing.py` (17 tests) includes a POST-without-token-rejected case. The original audit's finding (`flask_wtf` missing → no CSRF) is now stale: the app never adopted flask_wtf, it built an equivalent from stdlib `hmac`/`secrets` instead. |
| 3. Production data persistence | ✅ Already done, verified | `database/persistence.py` — SQLite online-backup API snapshots to `LocalDirStore`/`GcsStore`, restored on boot when the local DB file is missing, periodic + SIGTERM backup hooks. Fails closed at prod boot if neither `PERSISTENCE_BACKUP_BUCKET` nor `PERSISTENCE_BACKUP_DIR` is set. `tests/test_persistence.py` (7 tests) simulates a redeploy (delete local DB, reboot app, assert restored data matches) and passes. |
| 4. Account deletion + data export | ✅ Already done, verified | `routes/settings.py`: `GET /api/account/export` (`export_user_data()` in `db.py`, pulls every user-scoped table) and `POST /api/account/delete` (`delete_user()`, confirmation required, logs out session on success). `tests/test_memory_deletion.py` and export/delete coverage in `tests/test_privacy_csrf_landing.py` pass — deletion removes rows across tables, export is scoped to the requesting user only. |
| 5. Retire weak severity classifier from user-facing output | ✅ Already done, verified | `routes/api.py:44` strips `addiction_level_detail` from explanations; grepped every template/route/JS for the field — only reference outside the model-transparency/insights page and `ml/explainability.py`/`ml/predictor.py` internals is the exclusion logic itself. `tests/test_privacy_csrf_landing.py:205-227` and `tests/test_recovery_activities.py:430` assert the field's absence from dashboard/checkin/recovery API payloads. |
| 6. Privacy policy + consent at signup | ✅ Already done, verified | `templates/auth/signup.html:54` — required checkbox linking to `/privacy`; `routes/auth.py:72-103` blocks account creation without `consent_given`, logs `consent_at` timestamp per user. |
| 7. HTTPS / cookie hardening | ✅ Already done, verified | `config.py:_secure_cookie_default()` — `SESSION_COOKIE_SECURE` defaults True under `FLASK_ENV=production`/Cloud Run, False for local HTTP dev (documented rationale: Secure cookies are silently dropped over plain HTTP, which would break every session-based CSRF check locally). `DEPLOYMENT.md` documents the env var. |
| 8. Encryption at rest for journal/memory text | ✅ **Newly implemented this pass** | New `crypto_fields.py` (Fernet, key from `ENCRYPTION_KEY` env var, fails closed in production exactly like `SECRET_KEY`). Wired into `database/db.py`: `save_journal_entry`/`insert_memory_fact` now encrypt `journal_entries.entry_text` and `memory_facts.fact_text`/`normalized_text` before insert; every read path (`get_journal_entries*`, `get_active_memory_facts`, `find_similar_active_fact`, `export_user_data`) decrypts on the way out. `tests/test_encryption_at_rest.py` (5 tests, new): raw SQLite bytes for both columns contain no plaintext and carry the `enc:v1:` marker; normal read path still returns original plaintext; production boot without `ENCRYPTION_KEY` fails closed (subprocess-isolated test). `requirements.txt` and `DEPLOYMENT.md` updated. |

**Net effect on section 8's Security & Privacy Findings table and section 14's
scorecard below:** the Critical/High findings for items 1–7 (default secret key,
no CSRF, no deletion/export, wrong severity label, plaintext journal storage) were
already resolved before this pass and are stale in the table below as originally
written; the Medium "plaintext in SQLite" finding is resolved by item 8 above.
Phase 2 (nav trim, AI-honesty labeling, pricing-vs-reality) has **not** been
started as part of this pass.

---

## Phase 2 — Scope cut (this pass)

**Verification performed:** manual Flask test-client smoke script (no pytest available
in this environment — no network access, `pip install pytest` fails with no index
reachable). The script drives the real app (`create_app`) through signup → dashboard →
each hidden route, and asserts on the rendered HTML and status codes. It is not a
substitute for `python -m pytest -q`, which still needs to be run in an environment
with network access before merging — **the "150 passed" count from the prior pass has
not been re-confirmed against these changes.**

| Item | Status | Evidence |
|---|---|---|
| 9. Trim navigation to the core loop | ✅ Done, smoke-verified | `templates/base.html`: removed Games/Breathing, Focus Timer, Student Mode, What-If Simulator from the desktop "More" dropdown and the mobile menu; removed them from the `more_endpoints` active-state list. Moved Model Insights from the "More" dropdown to a footer link, gated `{% if session.get('user_id') %}` so it isn't newly exposed to logged-out visitors. Grepped every template/route/static file for `url_for('main.games')`, `url_for('main.focus_timer')`, `url_for('student.student_page')`, `url_for('tools.simulator_page')` — the only remaining reference is `templates/student.html:6`, an intentional in-page link from Student Mode to the Focus Timer (both already de-navved; not a broken nav dependency). Routes are unchanged (`routes/main.py:86-94`, `routes/student.py`, `routes/tools.py` untouched) — `/games`, `/focus`, `/student`, `/simulator`, `/insights` all still return 200 when hit directly, confirmed via smoke script. |
| 10. Make the AI layer honest / add cost controls | 🟡 Partially done | **Labeling:** confirmed already accurate going into this pass — `ml/chatbot.py`'s no-key fallback, `templates/companion.html:24` ("Deterministic, rule-based responses... no external AI model connected" vs "enhanced with an optional AI model"), and `templates/privacy.html:31` all correctly reflect live-vs-fallback state; no stray "AI-generated"/"Stub" claims found elsewhere (`dashboard.html`, `journal.html`, `faq.html`, `insights.html` greped clean). **Cost controls — newly added this pass:** `ml/chatbot.py` adds `GEMINI_DAILY_REQUEST_CAP` (default 30/user/day, env-overridable) enforced in both `get_chatbot_response` and `get_companion_response` before any live API call; once hit, the user transparently falls back to rule-based replies for the rest of the day (`daily_cap_reached: True` in the response) instead of the call going through uncapped. Each live call was already capped at `max_output_tokens` 300-400. Caveat: in-process dict, same single-worker limitation as the existing companion per-minute limiter — needs a DB/Redis-backed counter before a multi-worker deploy. **Eval set — newly added, NOT run against a live model:** `ml_pipeline/gemini_eval.py`, 20 prompts (everyday use + memory-recall pressure + diagnosis-bait + PII-bait), checked against real output for PII-shaped strings (email/phone/SSN regex) and diagnosis-sounding phrasing. This environment has no `GEMINI_API_KEY` and no network, so the script was only verified to run cleanly and correctly refuse to report a fake pass (`python -m ml_pipeline.gemini_eval` → exit 1, "No GEMINI_API_KEY configured... reports nothing rather than a fake pass"). **It has never been run against real Gemini output. Someone with a real key must run it and read the transcripts before flipping the live path on for real users — that gate is not yet closed.** |
| 11. Fix monetization to match what's real | ✅ Done | `templates/pricing.html`: replaced "Unlimited assessments / Personalized wellness reports / Priority support" with "Unlimited check-ins & assessments / Full assessment history & trends / Data export anytime" — matches `routes/settings.py`'s real export endpoint and `routes/billing.py`'s real unlimited-assessment gate (`is_premium_user()` bypassing `FREE_PLAN_DAILY_PREDICTION_LIMIT` in `routes/api.py:19`). Also discovered while fixing this: `generate_wellness_report()` (`ml/coach.py:68`, called unconditionally in `routes/api.py:40`) was **never actually gated behind premium in the code** — free users already got the same rule-based/AI report as premium users, just fewer assessments/day. So "personalized wellness reports" wasn't just unverified, it was factually not a premium-exclusive feature; removing it from the paid list is a correctness fix, not just a caution. No live Stripe charge is possible regardless (`routes/billing.py:41` returns a 400 "Payments aren't configured yet" without `STRIPE_SECRET_KEY`, which is unset in this environment) — the premium-list fix removes the promise even if a Stripe key were added later before the AI layer is ever eval-gated. |
| 12. Verification | 🟡 Partial | See "Verification performed" note above — manual smoke script only, real `pytest -q` not run (no network in this environment to install pytest). **Action needed: run `python -m pytest -q` in a networked environment and confirm the count is ≥150 (the prior pass's baseline) before treating Phase 2 as closed.** No test files were touched in this pass, and no existing test asserts on the removed nav links (grepped `tests/` for `games|focus_timer|simulator|student_page|Model Insights|What-If` — no matches), so a regression here is unlikely but not proven. |

**What's still open after this pass:**
- The Gemini eval set exists but has never seen real model output — run it and read the transcripts before turning the live path on.
- The daily cost cap is in-process only — fine for the current single-worker deployment, not for a multi-worker production one.
- `python -m pytest -q` needs to be re-run for real in a networked environment; this pass's changes were verified by a manual smoke script, not the actual suite.

---



## Classification legend

| Symbol | Meaning |
|---|---|
| ✅ | Shipped & verified working (tested and/or runtime-verified) |
| 🟡 | Works but limited — mocked, session-only, untested live, or degraded |
| 🔴 | Broken / would fail in the real world / misleading |
| 🟣 | Competence theater — exists to look impressive, no real user value |
| ⚪ | Stub / referenced but not built |

---

## 1. Complete Feature Inventory

### Core loop: assess → journal → plan
| # | Feature | Class | Evidence |
|---|---|---|---|
| 1 | Digital addiction risk assessment | ✅ | Runtime-verified `predict_all()`. `addiction_risk_flag`: LogisticRegression, test acc 0.817, ROC-AUC **0.911**, CV 0.828±0.016. The one genuinely good model. |
| 2 | Wellbeing score (0–10) | 🟡 | LinearRegression, R² ≈ 0.66–0.70. Functional, honestly disclosed, but a single weak number presented as a health metric. |
| 3 | Wellbeing risk flag | 🟡 | RandomForest, ~76–78%. Borderline-acceptable for a soft flag; disclosed as experimental. |
| 4 | Addiction level detail (Severe/High/Moderate/Low) | 🔴 | Model accuracy **~57–59%** — barely above chance on a 4-class label. It is SHIPPED and shown to users as a severity label. A coin-flip classifier labeling someone "Severe" is dangerous in a mental-health product. It is disclosed on the transparency page, which is credit-worthy — but it should not be user-facing output at all. |
| 5 | 21-feature check-in form | ✅ | Clean, free-tier gated (3/day). |
| 6 | Prediction history + trends (Plotly) | ✅ | Works, dashboard-verified. |
| 7 | Model transparency page (CV curves, feature importances, confusion matrices, "dead targets" disclosures) | ✅ | Genuinely rare honesty. Tells users exactly which 6 of 10 targets were dropped as worse than baseline. Its audience is mostly judges. |

### Journaling & emotion
| # | Feature | Class | Evidence |
|---|---|---|---|
| 8 | Journal + hybrid emotion analysis (lexical → VADER → transformer fallback chain) | ✅ | Tested. Works fully deterministically with zero API keys. Confidence, secondary emotion, sentiment breakdown, low-confidence flag. |
| 9 | Crisis detection + in-page banner | ✅ | Deterministic keyword trip, immediate banner, region-localized resources (PK/US/GB/IN/CA/AU + IASP/Befrienders directory fallback). Never shows a wrong-region phone number — unknown regions get directory links only. |
| 10 | Voice journaling | 🟡 | Client-side browser Web Speech API only, no audio uploaded/stored. Tracks `input_method` for adoption measurement (good instrumentation). Browser-dependent, silent for Firefox. |
| 11 | Journal word-cloud, mood calendar heatmap, streaks | ✅ | Dashboard-verified, streak logic handles "not yet journaled today" correctly. |

### Long-term memory (the real differentiator)
| # | Feature | Class | Evidence |
|---|---|---|---|
| 12 | Long-term AI memory: facts, occurrence counts, reinforcement, confidence, decay, context capping | ✅ | Full schema, ownership-checked deletes, "clear all". Tested (extraction, consolidation, deletion, retrieval, cross-user security). |
| 13 | Periodic summaries (so raw text isn't replayed) | ✅ | Schema + consolidation path exist. |
| 14 | User controls (delete fact, clear all) | ✅ | Real, scoped, confirmed in `db.py`. |
| 15 | Memory-fed personalization (recommendations, recovery plan suggestion) | 🟡 | Mechanism real, but quality depends on Gemini; canned without a key. |

### AI "assistant" surface
| # | Feature | Class | Evidence |
|---|---|---|---|
| 16 | Gemini chatbot / companion (dark chat UI, markdown, typing indicator, 15 msgs/60s rate limit) | ✅ | Works, rate limit tested (429 path), localized crisis resources in replies. **Rebranded (Phase 2 P0):** without a key the companion is now honest *deterministic, rule-based* responses — the product positioning, not a degraded stub. With a key: still zero production testing, no eval, no PII-guardrail evidence, **no cost controls** (still true — that's the opt-in path's open risk). |
| 17 | Dashboard "Wellness Assistant" widget | ✅ | **Resolved** — the "Stub — no live AI yet" badge is removed; the widget presents as the working Wellness Assistant. |
| 18 | AI daily coach, AI study plan, AI emotion explainer, AI FAQ | 🟡 | Rebranded copy (no "AI" pretension in UI; study plan/coach/reports described honestly). Deterministic fallbacks remain the default experience; Gemini stays an optional enhancement. |

### Risk & recovery
| # | Feature | Class | Evidence |
|---|---|---|---|
| 19 | Early risk engine (per-category scores, 90-day trend) | ✅ | Deliberately a transparent point-scoring heuristic, disclosed in UI and in schema comments ("not a trained classifier"). Honest and functional. **Must not be marketed as AI.** |
| 20 | Recovery plans + Activity Engine (10 interactive activity types, server-verifies completion, resumable, personalization loop from stored results) | ✅ | Best-engineered feature in the codebase. Tested. Real differentiation. |
| 21 | Habit tracker (15 max, idempotent check-ins, streaks) | ✅ | Simple, correct, ownership-checked. |
| 22 | Student mode (subjects, exams, assignments) | 🟡 | Works. Marginal — duplicates a thousand existing apps with no differentiator. |

### Engagement & gamification
| # | Feature | Class | Evidence |
|---|---|---|---|
| 23 | Badges, streaks, daily challenges | ✅ | Computed from real data. Cosmetic-only rewards. |
| 24 | Mini-games: breathing, bubble-pop, memory-match, Simon, reaction | 🟣 | All client-side, **scores live in a JS object — "kept for this session only" — zero persistence, zero connection to the product**. Impressive in a demo video; forgets you on reload. |
| 25 | Focus/Pomodoro timer | 🟣 | Same: client-only, no persistence. |
| 26 | Notifications (in-app bell) | 🟡 | Rule-based, dedupe-keyed. But in-app only — a "reminder" that requires the user to already be in the app. No push, no email without SMTP. Weak retention tool. |
| 27 | Weekly PDF report (reportlab) | 🟡 | Exists. Unverified live; delivery depends on SMTP. Real but dormant. |

### Monetization & business
| # | Feature | Class | Evidence |
|---|---|---|---|
| 28 | Stripe Checkout + subscription + webhooks + `subscription_events` | 🔴 | Full code, **zero live testing, no keys, explicitly "untested"**. UI degrades to *"Upgrade (demo — payments not configured)"*. Free-tier gate is a daily count; premium unlocks canned AI reports. Not revenue-ready. |
| 29 | Google OAuth (Authlib) | 🟡 | Implemented, untested, gracefully disabled without a client ID. |
| 30 | Referral program | 🔴 | Codes, tracking, "X people signed up" counter exist. **But there is no reward** — referrer gets nothing, referee gets nothing. A hollow counter. |
| 31 | Coupons (expiry, caps, one-per-user) | ✅ | Mechanically complete and correct server-side. |
| 32 | Admin dashboard (stats, plan overrides, coupons, testimonial approval, feedback, churn heuristic) | 🟡 | Works. No user ban/delete. "Churn risk" is a heuristic — honestly labeled. |
| 33 | Testimonials + feedback with approval flow | ✅ | Real, works. |
| 34 | Landing page / marketing site | 🔴 | **Does not exist.** `GET /` is `@login_required` → first-time visitors hit a login form. You cannot acquire users you can't explain the product to. |

### Platform & data
| # | Feature | Class | Evidence |
|---|---|---|---|
| 35 | Training pipeline / retraining | 🟢 | `ml_pipeline/final_train.py` + `evaluate.py` + `ml_pipeline/data/social_media_addiction_mental_wellbeing.csv` (1500 rows) committed. Versioned artifacts (SHA-256-pinned data, `final_metadata.json` v2), reproducible 80/20 split + 5-fold CV, and an eval script that reloads the saved artifacts and re-verifies every stored metric (all PASS). |
| 36 | Production data persistence | ✅ | **Resolved** — `database/persistence.py` backs up to GCS/local dir with restore-on-boot; `tests/test_persistence.py` verifies no data loss across a simulated redeploy. See "Trust-floor correction pass" item 3. |
| 37 | Email/SMTP delivery | 🟡 | Mailer prints to console in dev; password reset works locally without SMTP. Untested live. |
| 38 | CSRF protection | ✅ | **Resolved** — session-token CSRF (`security.py`) on every non-safe-method request, tested. See item 2 above. |

**Feature-count bottom line:** ~38 features. Roughly **14 are genuinely solid**, ~16 are "works but degraded/mocked", ~5 are actively broken or misleading, 3 are competence theater, 1 is absent. That is the profile of a **demo-first engineering showcase**, not a product.

---

## 2. Product Analysis

**What it actually is:** A single-user Flask/SQLite web app that (a) scores social-media addiction risk from a questionnaire, (b) journals and analyzes mood with a hybrid NLP stack, (c) builds a persistent "AI memory" of the user, (d) generates personalized recovery plans with interactive in-app activities, and (e) wraps it in streaks/badges/reports.

**What it is NOT:** A validated product. The DB has 1 user — the developer. Nothing about the product loop has been tested against another human being.

**The product thesis is coherent and defensible:** "smartphone addiction / digital wellbeing" is a real, growing, genuinely underserved mental-health niche, and the *memory → recovery-plan* loop is a legitimately interesting mechanic. But the thesis is diluted across ~38 features. The product can't decide whether it's a **digital addiction assessment**, a **mood journal**, a **habit tracker**, a **study planner**, a **games hub**, or a **wellness companion**. That is scope sprawl, and it shows: nothing is finished to the depth the niche demands.

**The single most damaging product fact:** the page a stranger lands on is a login form.

---

## 3. Market Analysis

- **Market size:** the "digital wellbeing / screen addiction" category is real (post-2020 screen-time anxiety, rising youth smartphone use). Consumer willingness to pay, however, is **unproven** — the category historically monetizes poorly (most screen-time apps are free, and Apple/Google now ship screen-time natively for free).
- **Competition density is brutal:** Apple Screen Time, Google Digital Wellbeing (free, OS-level, zero-friction), Opal, Space, JOMO, Flora, Forest, Moment. A paid web app must beat **free OS features** on outcomes, not features.
- **The strategic wedge that exists:** almost no competitor does **long-term memory + personalized recovery plans**. Apple and Google ship usage timers, not an understanding of *you*. That gap is real — but only if the AI layer is real, which today it isn't (canned).
- **Regulatory gravity:** mental-health-adjacent data in the EU = GDPR; in the US = FTC health-breach rules and, if diagnosis-adjacent, FDA risk. "Digital addiction severity labels" are the riskiest possible output to ship from a 57%-accurate model.

---

## 4. Customer Analysis

- **Real users today:** 1 (the developer).
- **Target customer implied by the product:** a young, high-screen-time student who (a) self-screens for addiction, (b) journals, (c) wants structure to cut down.
- **Who pays:** the $9/mo premium unlocks *unlimited assessments* and *AI wellness reports*. Nobody has been asked whether that's worth $9/mo. There is no evidence of willingness to pay anywhere in the repo.
- **The honest segmentation:** the first 100 users of a mental-health app built by a student are almost certainly *other students in their own university network*. Everything about the current product (US-only crisis lines, no onboarding, no landing page, English-only, generic features) is misaligned with that actual first market.
- **Missing entirely:** any onboarding, any persona-driven flows, any evidence of a single user interview. The product is built from an imagined persona, not a contacted one.

---

## 5. Competitive Differentiation

**What is genuinely different (keep):**
1. **Long-term memory + personalized recovery plan loop.** No mainstream player does this. This is the only real moat-seed in the repo.
2. **Radical transparency** (dead-model disclosures, heuristic honesty). Authentically rare and, in a mental-health category plagued by AI-washing, could become a trust brand.
3. **Activity Engine** — plans that aren't checklists but actual in-app work (journal, breathing, guided reflection, screen-free timers).

**What is NOT different (delete or de-emphasize):**
- Habit tracker (everyone has one).
- Student planner (hundreds of better ones).
- Mini-games (OS-level games and 100k app-store games beat toy JS games).
- Mood journaling with sentiment (commodity).
- "AI" companion (everyone claims one; yours is canned).

---

## 6. AI/ML Audit

| Model | Algorithm | Key metric | Verdict |
|---|---|---|---|
| `addiction_risk_flag` | LogisticRegression | test acc 0.817, **ROC-AUC 0.911**, CV 0.828±0.016 | ✅ Genuinely good |
| `addiction_level_detail` | (multi-class) | **~57–59% accuracy** | 🔴 Below the bar for user-facing severity labels |
| `wellbeing_score` | LinearRegression | R² ≈ 0.66–0.70 | 🟡 Weak but usable as a trend |
| `wellbeing_risk_flag` | RandomForest | ~76–78% | 🟡 Soft flag, borderline |

**Structural problems:**
1. **No training pipeline.** `final_train.py` is referenced but doesn't exist. No CSV, no dataset versioning, no reproducibility. The 4 models are frozen artifacts with no path to improvement.
2. **No eval harness.** The numbers above are one-time snapshots in a metadata JSON. Nothing re-runs evaluation.
3. **6 of 10 targets were dropped** for being worse than a naive baseline. The codebase was honest enough to record this. A startup should read this as: *half the product's ML promises don't survive contact with data.*
4. **The Gemini layer is unverifiable.** Canned fallbacks work; real-key behavior is untested, unevaluated, uncosted, unguardrailed. There is no prompt eval set, no PII redaction check, no hallucination test.
5. **"AI" branding vs reality.** Risk engine = deterministic rules (fine, honest). Churn = heuristic (fine, honest). But the *perception* problem is real: a product with 4 weak-ish models + canned LLM responses presenting "AI reports" as premium is exactly the AI-washing the mental-health space is under regulatory pressure over.

---

## 7. Technical Readiness

**Strengths (real, not padded):**
- Clean architecture: `database/db.py` is a deliberately swappable stdlib-sqlite layer ("only this file changes" for Postgres).
- **72 passing tests** across memory, security/ownership, Gemini-failure fallbacks, recovery activities, rate limiting. This is unusually good for a student project.
- Consistent ownership-checking on all per-user mutations (idempotent, user-scoped, 404-vs-reveal discipline).
- Careful migration strategy (`_migrate_existing_db`) with honest backfill logic.
- Runtime-verified: app boots, predictions flow, dashboard data aggregates.

**Failures that block real deployment:**
1. **SQLite on Cloud Run = data loss by design.** The intended production deployment wipes all user data on redeploy. This is the #1 technical blocker, not an "ops nicety."
2. **No landing page at `/`** (product blocker).
3. **Feature sprawl** — 17 blueprints, ~38 features, one developer. Breadth is running at the expense of depth.
4. **No CI**, no container image in the repo, no deployment script — the deployment story is a markdown document.
5. **In-process rate limits** (companion, daily assessment counts) don't survive restarts and don't work across multiple gunicorn workers — fine for a demo, wrong for a product.

---

## 8. Security & Privacy Findings (with severity)

| Severity | Finding | Location |
|---|---|---|
| ~~**Critical**~~ | ~~Default `SECRET_KEY = "dev-key-change-in-production"` — sessions are forgeable if deployed without setting env.~~ **Resolved** — fails closed in production instead of defaulting. See "Trust-floor correction pass" item 1 above. | `config.py` |
| ~~**High**~~ | ~~No CSRF protection on any state-changing endpoint~~ **Resolved** — session-token CSRF on every non-safe method. See item 2 above. | `security.py` |
| ~~**High**~~ | ~~No account deletion, no full data export~~ **Resolved**. See item 4 above. | `routes/settings.py`, `db.py` |
| **High** | A 57%-accurate severity classifier labeling real users "Severe/High" is a safety bug, not just an accuracy bug. **Model itself is unchanged (still ~57–59% accurate) — but it no longer reaches user-facing output**, only the model-transparency page. See item 5 above. | `ml/artifacts` |
| **High** | ~~US-only crisis resources (988, 741741) served to a global/international audience. Wrong phone numbers in a crisis are a real harm.~~ **Resolved** — `ml/crisis_resources.py` serves per-country resources (PK/US/GB/IN/CA/AU) and falls back to IASP/Befrienders directory links for unknown regions; journal banner, companion chat, and FAQ all region-aware. | `routes/journal.py` |
| ~~**Medium**~~ | ~~`SESSION_COOKIE_SECURE` defaults off~~ **Resolved** — defaults on in production/Cloud Run. See item 7 above. | `config.py` |
| ~~**Medium**~~ | ~~Journal text, memories, and PII stored plaintext in SQLite; no encryption at rest.~~ **Resolved this pass** — field-level encryption via `crypto_fields.py`. See item 8 above. | `db.py`, `crypto_fields.py` |
| ~~**Medium**~~ | ~~No privacy policy, no consent checkbox, no data-processing disclosure found.~~ **Resolved** — required consent checkbox at signup, logged timestamp, links to `/privacy`. See item 6 above. | `routes/auth.py`, `templates/auth/signup.html` |
| **Medium** | Password reset link is emailed only via SMTP; in dev the token prints to console (acceptable for dev, must not ship). | `ml/mailer.py` |
| **Medium** | `referral_code` derived from `name` + 12 bits of hex — guessable/abusable for the hollow referral feature. | `db.py:338` |
| **Low** | Stored XSS surface via rendered journal/feedback content — appears to use escaping, but no Content-Security-Policy header seen. | base templates |

**What's done RIGHT:** password hashing (werkzeug), anti-enumeration on password reset, per-user ownership checks on every mutation, `secrets.token_urlsafe` for reset tokens, idempotent webhook logging, input length caps everywhere, no secrets in frontend JS.

---

## 9. UX Trace

The intended happy path, walked from the code:

1. **Arrival:** `GET /` → `@login_required` → **redirect to login.** A stranger cannot learn what the product is. *(Fatal.)*
2. **Signup:** name/email/password + optional referral code. No email verification, no consent, no onboarding questions. *(Functional but cold.)*
3. **First action after signup:** dumped on the **dashboard** — stat cards with empty/zero values, a blank wellbeing chart ("Run a few predictions to see your trend"), an empty habit area, and a chat widget labeled **"Stub — no live AI yet."** The first-run dashboard is an empty shell. There is no guided "start here."
4. **Assessment:** `/checkin` → 21 questions → results with at-risk probability + wellbeing score. *This works and is the strongest first moment — but nothing forces the user toward it.*
5. **Journal:** write → emotion + breakdown + optional voice. *Solid.*
6. **Recovery plan:** risk screen suggests → plan with day-by-day activities in modal. *The best moment in the product.*
7. **Return:** dashboard streaks/badges/heatmap, in-app notification bell.

**Verdict on the trace:** the **middle of the funnel is excellent** (assessment → journal → plan), but the **top is broken** (no landing page, no onboarding, empty first-run dashboard) and the **reengagement loop is weak** (in-app-only notifications, no email, nothing actionable pulling a user back).

---

## 10. Retention

- **Good bones:** streaks, badges, daily challenges, recovery plans with day-gated progress, weekly PDF report, long-term memory that makes the app *smarter with use*.
- **Killers:** (a) reminders that only reach users already inside the app; (b) the most retention-worthy feature (memory-fed personalization) is canned without a key; (c) games and focus timer persist nothing, so their "engagement" resets every session; (d) the free tier (3 assessments/day) may actually *limit* the habit-forming daily check-in.
- **Realistic numbers:** with zero real users there are no retention numbers to critique — the honest statement is that the design *intends* retention but nothing has ever been measured. Streak logic is correct; whether anyone returns for day 4 is untested.

---

## 11. Monetization

- **Mechanism:** free (3 assessments/day) vs **$9/mo premium** (unlimited + "AI wellness reports"). Stripe Checkout, coupons, webhook idempotency all coded. **Nothing has ever been charged.** No keys, no test-mode validation, no live run.
- **The core problem:** the paywall unlocks *canned AI reports* and *an unlimited counter*. There is no validated reason anyone pays $9/mo for that.
- **The only defensible premium later:** the real (Post-Phase-2) AI layer — memory-fed weekly insights, personalized plans beyond templates, data export/backup, multi-device sync. Monetize the moat, not the mock.

---

## 12. Distribution

- **Current state:** a login wall at `/`, no landing page, no SEO, no social sharing, no email capture, a referral system with **no incentive on either side**, and a mindset (DEPLOYMENT.md) explicitly aimed at a *competition demo*.
- **The realistic first channel:** the developer's own university/student network. A digital-addiction app for students, launched on a campus, with a real onboarding loop and honest US-free crisis localisation, is the only plausible first-100-users path here.
- **Growth loop that could actually exist:** a shareable "your digital wellbeing score" card from the assessment (with opt-in). The category is inherently social-comparison fuel; that's the one organic loop in reach.

---

## 13. Defensibility

- **Weak:** the models are commodity (and under-trained); the features clone easily; there is no proprietary data and no network effect.
- **The only real seed of a moat:** **accumulated long-term memory + personalization.** A user's history in this app is genuinely hard to replicate elsewhere because it's theirs and it compounds. If the AI layer is made real, this is a defensibility story. Today, with canned responses, the moat is ornamental.
- **Honest verdict:** defensibility today ≈ 0. Defensibility in 12 months ≈ real *if and only if* the memory + honest-AI thesis is executed.

---

## 14. Startup Scorecard (0–10)

| # | Category | Score | One-line reason |
|---|---|---|---|
| 1 | Product-market fit | **1** | 1 user, zero evidence of demand |
| 2 | Engineering quality | **7** | Clean, tested (72), honest architecture — genuinely strong |
| 3 | Core ML quality | **3** | One great model, one dangerous one, no pipeline |
| 4 | Data infrastructure | **2** | No training data, no pipeline, ephemeral prod DB |
| 5 | UX / design | **6** | Polished UI, but login-first and empty first-run |
| 6 | Security | **7** *(was 2)* | Fail-closed SECRET_KEY/ENCRYPTION_KEY, real CSRF, secure-cookie enforcement in prod — all verified this pass. Remaining gap: Stripe/OAuth still untested live. |
| 7 | Privacy / health-data trust | **6** *(was 1)* | Deletion + export + consent + encryption at rest all shipped and tested. Remaining gap: the 57%-accurate classifier still exists in the model artifacts (just no longer user-facing), and crisis-region coverage is 6 countries + directory fallback, not universal. |
| 8 | Retention mechanics | **4** | Good bones, no delivery channel, session-only games |
| 9 | Monetization | **2** | $9/mo for canned AI, never charged a cent |
| 10 | Distribution | **1** | No landing page, no channel, no incentive referral |
| 11 | Defensibility | **2** | Moa only exists if memory-AI becomes real |
| 12 | Regulatory / safety readiness | **1** | 57% classifier labeling severity to vulnerable users |
| 13 | Scope control / team realism | **2** | ~38 features, one developer, no prioritization |
| 14 | Honesty & transparency | **9** | The best quality in the codebase; rare and valuable |
| | **Average** | **3.1 / 10** | |

---

## 15. Three Verdicts

1. **Is it shippable to real users today?** **NO.** Fatal blockers: no landing page, ephemeral data, default secret key, no CSRF, no privacy/deletion story, a 57% severity classifier in user-facing output, and a "Stub — no live AI yet" label on the flagship widget.
2. **Is it a strong competition/demo project?** **YES — arguably near-winning.** 72 passing tests, honest ML disclosure, a genuinely innovative recovery/activity engine, real memory mechanics, and runtime-verified features put this in the top tier of student projects. This is what the project *actually is* right now.
3. **Is it a fundable / viable startup as-is?** **NO.** The market is brutal (free OS-level competition), the revenue story is unvalidated, and the differentiator is currently canned. It is a promising **prototype in search of a product decision**, not a business.

---

## 16. Prioritized Roadmap

### Phase 1 — Foundation & trust (before ANY real user) — all P0
- **P0 Landing page at `/`** — move the app behind `/dashboard`; build a real marketing page (problem, how it works, privacy, signup). Nothing else matters if strangers can't learn what this is. *(Not touched by the trust-floor correction pass — still open.)*
- **P0 Fix the deployed-data guarantee** — **DONE**, see correction-pass item 3.
- **P0 Security hardening** — **DONE**, see correction-pass items 1, 2, 7.
- **P0 Privacy floor** — **DONE**, see correction-pass items 4, 6, 8 (deletion, export, consent, encryption at rest).
- **P0 Remove the 57% severity classifier from user-facing output** — **DONE**, see correction-pass item 5.
- **P1 Localize crisis resources** — IASP per-region directory; never show a wrong-region phone number. **DONE** (`ml/crisis_resources.py` + `users.country_code` set at signup/Settings; 19 tests).

### Phase 2 — Make the AI honest (P0/P1)
- **P0 Decide the AI story, then execute it** — **DONE** (chose path b): rebranded as "deterministic rules + your journal memory", removed the "Stub — no live AI yet" badge and every canned-AI confession from the UI; Gemini is now an honest optional enhancement. 7 tests in `tests/test_ai_rebrand.py`.
- **P1 Build a real dataset + training pipeline** for the one model that matters (addiction risk), with versioned artifacts and an eval script that can re-run the 0.911 AUC. **DONE** — `ml_pipeline/final_train.py` (trains all 4 models from `ml_pipeline/data/social_media_addiction_mental_wellbeing.csv`, 1500 rows, deterministic 80/20 split, 5-fold CV, SHA-256-pinned data, regenerates `ml/artifacts/` + `final_metadata.json` v2) and `ml_pipeline/evaluate.py` (reloads the saved artifacts and re-verifies every stored metric). Re-run: AUC 0.911 → **0.926**; flag accuracy 0.817 → **0.857**; `python -m ml_pipeline.evaluate` → all PASS.
- **P1 Retire or replace the R² 0.66 wellbeing score** with an interpretable composite, or drop it. **KEPT by owner decision** — model is honest + reproducible now: a 7-family CV sweep (`model_comparison` in metadata) shows all linear families tie at CV R² ≈ 0.65 and trees/SVR are worse; the interpretable LinearRegression is retained (test R² 0.67, MAE 0.57, "moderate" tier) and only replaced if a family beats it by ≥ 0.005 CV R².
- **P2 Add real onboarding**: first-visit guided flow (one assessment → explain results → one journal entry) instead of the empty dashboard. **DONE** — `/onboarding` 3-step flow (data-derived state, no schema change): brand-new accounts get `/dashboard` → `/onboarding` redirect, steps for Check-In → results (automatic, with explanations) → first journal entry, progress banners on `/checkin?onboard=1` and `/journal?onboard=1`, next-step CTA after results and a completion card after the first entry. 7 tests in `tests/test_onboarding.py`.

### Phase 3 — Retention & revenue (only after Phase 1–2) — P1/P2
- **P1 Real email delivery** (transactional: password reset, weekly report, re-engagement nudges). The in-app bell is not a reminder system. **DONE (code)** — `ml/mailer.py` rebuilt: STARTTLS (587) + implicit TLS (465) via `SMTP_USE_SSL`, HTML+plain emails, timeout + failure-capture, console-print dev fallback; new `send_weekly_report_email()` (7-day summary + PDF link) wired to a `POST /reports/email` route and a dashboard "Email me this report" button; `.env.example` documents all SMTP vars. **Still needs you:** set real `SMTP_*` env vars and confirm one live send (7 tests cover both send paths via a fake SMTP server).
- **P1 Persist or cut the games** — keep breathing, fold one "focus check-in" into the recovery plan, delete the other four. Session-only scores are engagement theater. **DONE** — the 4 arcade games (Reaction Test, Simon Says, Memory Card Match, Bubble Pop) and their JS are deleted; `/games` is now a single Paced Breathing page. Focus/breathing/check-in were already first-class activities inside Recovery Plans (`timer`/`breathing`/`checkin` activity types + `/api/recovery/activities/.../timer` and `/breathing` endpoints), so the "focus check-in" lives in the plan, not as standalone score theater.
- **P2 Make the referral real** (both sides get premium days) or delete it. A dead counter is worse than no referral program. **DONE** — a valid referral code at signup now grants both sides **7 Premium days** (`REFERRAL_PREMIUM_DAYS`, stacking on existing `premium_until`), logged as `premium_grant` events in `subscription_events`. Introduced a date-based `users.premium_until` (migrated via `_migrate_existing_db`) and a single `is_premium_user()` gate (plan `premium` **or** future `premium_until`); the free 3/day limit on `/api/predict` and the recovery-plan assessment path now honors premium (previously keyed off the stale `plan` column, so paid users were still throttled). Signup flashes the reward; the Feedback page says what the link is worth. Invalid codes are ignored, no crash. 8 tests in `tests/test_referral_premium.py`.
- **P2 Charge for the actual moat** — premium = real memory-fed weekly insights, multi-device sync, unlimited assessment history. Not canned reports.
- **P3 Re-test the free limit** — 3 assessments/day may strangle the daily habit loop. **DONE (raise + configurable)** — default raised **3 → 5** (`routes/billing.py`, overridable via `FREE_PLAN_DAILY_PREDICTION_LIMIT` env var); the limit now correctly applies on `/api/predict` *and* the recovery-plan assessment path, and both honor premium via `is_premium_user()`. `pricing.html` reads the constant, so copy stays truthful. Verified by `test_free_user_hits_api_limit_after_free_daily_limit`.

### Phase 4 — Distribution & validation — P1/P2
- **P1 Launch into the first real market**: the developer's own university network. Offline campus distribution beats every ad dollar available to a solo student.
- **P2 Shareable outcome card** (opt-in "digital wellbeing score" image) as the only credible organic growth loop.
- **P2 Wire or remove the "Stub — no live AI yet" label** — a user-facing stub tag on the flagship chat widget is disqualifying either way. **DONE** — label removed as part of the Phase 2 AI-story rebrand.

---

## 17. What NOT to Build

- **No mobile app** — no need; the web app plus a phone-usable UI covers the demo and the first 100 users.
- **No wearables / HealthKit / Health Connect** — nobody has proven the core loop yet.
- **No social feeds or anonymous communities** — moderation and safety liability you cannot take on.
- **No more mini-games or gamification layers** — fix the one breathing activity, cut the rest.
- **No more Gemini features** — the existing AI surface must be made real and evaluated before any new one.
- **No therapy marketplace / licensed-clinician features** — a liability cliff with zero upside for a student team.
- **No video/audio journal storage** — cost + safety + storage liability.
- **No expanded student mode** (flashcards, study timers, planners) — not the differentiator.
- **No clinic/enterprise dashboards** — you have no clinical credibility or channel.
- **No retraining the 6 dropped targets** — the data said no; believe it.
- **No app-store presence, no content recommendation engine, no "premium content library."**

---

## 18. Final Founder Verdict

> **VERDICT: NO — not as a startup today. YES — as the strongest thing you'll ever make if you make one product decision and finish it.**

**Why NO:** nothing in the repo has been validated against another human being. There is 1 user. There is no landing page, no way to be found, no privacy floor, no durable data, and the one paid feature is a canned AI report. Raising money or charging users for that would be a mistake.

**Why it's worth continuing (not as a hobby):** the raw engineering quality is exceptional for a student project — 72 passing tests, honest ML disclosure, a genuinely novel memory→recovery-plan loop. The difference between this and most student projects isn't skill; it's that the skills are real. What's missing is **decisions**, not ability.

**What would change the verdict:**
1. One decisive product focus: **digital-addiction assessment → long-term memory → personalized recovery**, everything else cut or dormanted.
2. Phase 1 completed (landing page, durable data, security, privacy, remove the 57% label, crisis-resource localization).
3. One of the two AI paths honestly executed — **DONE** (honest rule-based, Phase 2 P0), not the canned in-between.
4. **100 real users** — students in your own network — with measured retention before any further building.

**The brutal summary:** right now this is a near-winning *competition project* being pitched as a startup. Make the four decisions above, ship to 100 humans, and you'll have a real answer — until then, every additional feature you add is a delay on the only metric that matters: another human's week of usage.

---

*Audit performed against the code as it exists. All claims traceable to files and runtime checks. Original test run: `python -m pytest -x -q` → 72 passed. Trust-floor correction pass test run: `python -m pytest -q` → **150 passed** (see addendum above).*
