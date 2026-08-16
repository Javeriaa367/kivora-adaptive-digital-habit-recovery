# Kivora — Adaptive Digital Habit Recovery

A full-stack Flask web application that helps users understand and manage
unhealthy digital/social-media habits through risk prediction, guided
journaling, and personalized recovery plans.

## Problem it solves

Most "screen time" tools just report numbers. Kivora goes further: it
models a user's risk level from their behavior and mood data, explains
*why* that risk was flagged, and adapts a recovery plan around it —
combining a trained ML risk engine with journaling, habit tracking, and
an AI companion for support.

## Key features

- **Risk prediction engine** — trained scikit-learn models (`ml/artifacts/`)
  estimate addiction risk and wellbeing score from user check-in data, with
  an explainability layer (`ml/explainability.py`, `ml/emotion_explainer.py`)
  so predictions aren't a black box
- **Adaptive recovery plans** — recovery activities and plans selected per
  user based on their risk profile (`ml/recovery_plans.py`, `ml/selector.py`)
- **Journaling with emotion analysis** — a hybrid pipeline (VADER +
  transformer model + lexical fallback) analyzes journal entries
  (`ml/emotion_analyzer_hybrid.py`)
- **AI companion / chat coach** — Gemini-backed chat and study coach with
  crisis-resource safeguards (`ml/chatbot.py`, `ml/crisis_resources.py`)
- **Habit tracking, gamification, weekly PDF reports**
- **Authentication, encrypted-at-rest journal fields, CSRF protection,
  role-based admin panel** — see `security.py`, `crypto_fields.py`,
  `auth_utils.py`
- **Billing integration (Stripe)** and **Google OAuth login** (both
  implemented, marked untested-live in `requirements.txt`)
- **Real test suite** — 25+ files under `tests/`, plus `pytest.ini`

## Tech stack

- **Backend:** Python, Flask (blueprint-per-feature architecture)
- **ML:** scikit-learn, pandas, numpy, joblib
- **NLP:** VADER sentiment, HuggingFace `transformers`
  (`j-hartmann/emotion-english-distilroberta-base`)
- **AI:** Google Gemini API (`google-genai`)
- **Database:** SQLite, with optional GCS-backed durable persistence for
  Cloud Run deploys (`database/persistence.py`)
- **Security:** field-level encryption (`cryptography`), CSRF, secure
  session cookies, fail-closed config in production (`config.py`)
- **Other:** Stripe billing, Authlib (Google OAuth), ReportLab (PDF
  reports), Gunicorn

## How it works

1. A user completes onboarding/check-in data collection.
2. The risk engine (`ml/risk_engine.py`) runs trained models against that
   data to produce a risk flag and wellbeing score.
3. `ml/recommendations.py` / `ml/selector.py` map that output to a
   personalized set of recovery activities and interventions.
4. Ongoing journal entries feed the emotion-analysis pipeline, which
   updates recommendations and surfaces insights over time.
5. `security.py` enforces CSRF on every state-changing request via a
   `before_request` hook registered in `app.py`.

## Project structure (top level)

```
app.py                 # App factory, blueprint registration
config.py               # Environment-driven config, fails closed in prod
security.py              # CSRF validation
crypto_fields.py          # Field-level encryption for sensitive data
auth_utils.py
database/                # DB init + durable persistence (GCS backup/restore)
ml/                      # Risk engine, recovery plans, chatbot, emotion analysis
ml_pipeline/             # Model training/evaluation scripts + dataset
routes/                  # One blueprint per feature area (auth, journal,
                          # habits, billing, admin, companion, risk, ...)
templates/, static/       # Views and assets
tests/                   # pytest suite
DEPLOYMENT.md             # Google Cloud Run deployment guide
STARTUP_AUDIT.md          # Startup/config audit notes
```

> Note: this repo also contains a `kivora_hardened/` directory — an
> in-progress hardened variant kept alongside the main app. It isn't part
> of the primary app entry point described above.

## Installation & setup

```bash
git clone https://github.com/Javeriaa367/kivora-adaptive-digital-habit-recovery.git
cd kivora-adaptive-digital-habit-recovery
pip install -r requirements.txt

# Optional, for the full hybrid emotion-analysis pipeline:
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Create a `.env` file (loaded automatically via `python-dotenv`):

```
SECRET_KEY=<generate with: openssl rand -hex 32>
ENCRYPTION_KEY=<your encryption key>
GEMINI_API_KEY=<your Gemini API key>
# Optional: STRIPE_SECRET_KEY, GOOGLE_CLIENT_ID/SECRET, PERSISTENCE_BACKUP_*
```

`SECRET_KEY` and `ENCRYPTION_KEY` are required in production (`FLASK_ENV=production`
or when running on Cloud Run) — the app fails to start without them, by design.

## Usage

```bash
python app.py
```

For a Cloud Run deployment, see `DEPLOYMENT.md`, which includes a ready
Dockerfile and durable-persistence setup for the SQLite database.

## Screenshots / demo

Screenshots of the running app (landing, dashboard, journaling, risk
insights, recovery plan, admin panel, etc.) are available in the
[portfolio site](https://github.com/Javeriaa367/javeria-portfolio) under
`static/images/kivora/`.

## Live demo

*[Add a live deployment link here if/when one exists — none found in this repo.]*

## Future improvements

*[Add your own roadmap here — e.g. live Stripe/OAuth testing, resolving
the duplicate `kivora_hardened/` directory, a Dockerfile in the repo
itself rather than only documented in DEPLOYMENT.md.]*

## Author

**Javeria** — CS student focused on Python, Flask, and applied ML.
GitHub: [@Javeriaa367](https://github.com/Javeriaa367)
