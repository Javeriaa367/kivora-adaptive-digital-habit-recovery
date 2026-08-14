# Google Cloud Deployment

This app already uses one Google Cloud product: **the Gemini API**
(`ml/chatbot.py`, `ml/coach.py`, `ml/study_coach.py`, `ml/faq.py`) — the
same API that backs Vertex AI's Gemini models, just via the simpler
direct API instead of the full Vertex AI SDK. If your competition rubric
specifically wants Vertex AI branding rather than the direct Gemini API,
swap `google-genai` for `google-cloud-aiplatform` and initialize with a
project/location instead of an API key — the prompts and response
handling in those 4 files stay the same either way.

Below is the actual path to deploy this app on **Cloud Run**, which is
the natural fit for a Flask app like this (scales to zero, no server
management, cheap for a demo/competition deployment).

## 1. Prerequisites

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com artifactregistry.googleapis.com
```

## 2. Add a Dockerfile

Not included by default (this project ships as a plain Flask app you run
with `python app.py`). Add this at the project root:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
ENV PORT=8080
CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 60 app:app
```

## 3. Durable data (SQLite + automatic backup/restore)

Cloud Run's filesystem is **ephemeral** — a bare SQLite file is wiped on
every redeploy. That is no longer the shipped behavior: `database/db.py`
still uses stdlib SQLite, but `database/persistence.py` wraps it so user
data (journals, memories, recovery plans) survives redeploys:

- **Restore on boot** — every boot pulls the newest backup down first if
  the local DB file is missing (which is exactly the redeploy case).
- **Scheduled backup** — the newest write is backed up within
  `PERSISTENCE_BACKUP_INTERVAL` seconds of the last request.
- **Shutdown backup** — a final backup runs on SIGTERM/SIGINT (what
  Cloud Run sends when an instance is retired).
- **Consistent snapshots** — backups go through sqlite3's online backup
  API (`Connection.backup`), safe to take while the app is writing.

Two durable stores, chosen by env var:

- **Google Cloud Storage (recommended for Cloud Run)** —
  `PERSISTENCE_BACKUP_BUCKET=my-bucket`. Uses the `google-cloud-storage`
  client with Cloud Run's Application Default Credentials — no keys in
  the image.
- **Local directory / mounted volume** — `PERSISTENCE_BACKUP_DIR=/path`
  (e.g. a Filestore mount, or any path that outlives the container).
  Simpler; single-instance only.

**Fail-closed:** a production boot (`FLASK_ENV=production`, or on Cloud
Run) with neither store configured refuses to start, so you can't
silently ship the old data-loss behavior. Local dev runs with no
persistence unless you opt in.

## 4. Backup & restore procedure

Create the bucket once (one-time setup):

```bash
gcloud storage buckets create gs://YOUR_PROJECT_ID-mindmetrics-backups \
  --location=us-central1
```

The Cloud Run runtime service account needs write access. If your
service runs as the default compute SA, grant it:

```bash
gcloud storage buckets add-iam-policy-binding \
  gs://YOUR_PROJECT_ID-mindmetrics-backups \
  --member="serviceAccount:YOUR_PROJECT_ID-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

Point the service at it in the deploy command (section 5):

```bash
--set-env-vars="PERSISTENCE_BACKUP_BUCKET=YOUR_PROJECT_ID-mindmetrics-backups"
```

How it fits together:

- Backup objects: `gs://<bucket>/mindmetrics-backups/app.db.<UTC timestamp>.bak`
- Names sort lexicographically, so the **newest object is the restore point**.
- Restore is automatic on every boot when the local DB is gone — no manual step on redeploy.

Manual restore (e.g. after a bad migration, or to recover a deleted row):

```bash
# list restore points
gcloud storage ls gs://YOUR_PROJECT_ID-mindmetrics-backups/mindmetrics-backups/

# pull a specific one and boot the app against it
gcloud storage cp gs://.../mindmetrics-backups/app.db.<timestamp>.bak ./restored.db
DATABASE_PATH="C:\absolute\path\restored.db" python app.py   # or export DATABASE_PATH=/path/restored.db
```

Retention: backups are never auto-deleted, so add a lifecycle rule to
stop the bucket growing forever (here: keep 30 days):

```bash
gcloud storage buckets update gs://YOUR_PROJECT_ID-mindmetrics-backups \
  --lifecycle-file=- <<'EOF'
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30}}]}
EOF
```

Honest caveats:

- The loss window is bounded by `PERSISTENCE_BACKUP_INTERVAL` (default
  120s) plus time since the last request; the SIGTERM shutdown backup
  covers the tail on normal shutdowns.
- SQLite is single-writer by nature, so this is a **single-instance**
  design. Keep `--min-instances=1` (already in the deploy command below).
  Multiple gunicorn workers inside one instance share the same SQLite
  file fine; each worker also takes its own backups, which is harmless
  (just redundant objects).
- The GCS store follows the `google-cloud-storage` contract and is wired
  exactly like the project's other cloud features (Stripe, Gemini) —
  which is to say **not live-tested from this sandbox**. Verify once
  against a real bucket before trusting it in production.

## 5. Secrets

Never bake API keys into the Docker image. Use Secret Manager:

```bash
echo -n "your-gemini-key" | gcloud secrets create gemini-api-key --data-file=-
echo -n "your-stripe-key" | gcloud secrets create stripe-secret-key --data-file=-
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
  | gcloud secrets create encryption-key --data-file=-
```

Then reference them at deploy time (below), not in `requirements.txt` or
any committed file.

`encryption-key` (env var `ENCRYPTION_KEY`) is the field-level encryption
key for journal entries and memory facts (see `crypto_fields.py`). Treat
it like `SECRET_KEY`: generate it once, store it only in Secret Manager,
and never rotate/lose it without a migration plan — losing it makes every
existing journal entry and memory fact permanently undecryptable. The app
refuses to boot in production without it set, same as `SECRET_KEY`.

## 6. Deploy

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/mindmetrics

gcloud run deploy mindmetrics \
  --image gcr.io/YOUR_PROJECT_ID/mindmetrics \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --min-instances=1 \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest,STRIPE_SECRET_KEY=stripe-secret-key:latest,ENCRYPTION_KEY=encryption-key:latest" \
  --set-env-vars="SECRET_KEY=$(openssl rand -hex 32),PERSISTENCE_BACKUP_BUCKET=YOUR_PROJECT_ID-mindmetrics-backups"
```

(The `PERSISTENCE_BACKUP_BUCKET` env var is what makes user data survive
redeploys — see section 4.)

## 7. Stripe & Google OAuth redirect URLs

Once deployed, Cloud Run gives you a URL like
`https://mindmetrics-xxxxx-uc.a.run.app`. Update:
- Stripe webhook endpoint -> `<that-url>/api/billing/webhook`
- Google OAuth authorized redirect URI -> `<that-url>/auth/google/callback`

## 8. Logging & Monitoring

Cloud Run sends stdout/stderr to Cloud Logging automatically — no code
change needed. For anything beyond default request logs (e.g. tracking
prediction volume, crisis-flag rate over time), query Cloud Logging or
wire up Cloud Monitoring alerts on log-based metrics.

---

**None of this has been tested end-to-end** — no live GCP project or
credentials in the sandbox this was written in. Treat it as a documented
starting point, verify each step against current `gcloud`/Cloud Run docs
before your competition deployment. The SQLite data-loss question from
the old step 3 is now handled in code (`database/persistence.py`, tested
locally — see `tests/test_persistence.py`); what remains unverified is
the live GCS handshake in section 4.
