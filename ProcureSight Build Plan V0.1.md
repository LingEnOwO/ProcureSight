# ProcureSight Build Plan v0.1

> AI‑assisted invoice & contract intelligence with anomaly alerts (ETL → extract → validate → score → notify)

---

## 0) What you’ll have at the end

- A working monorepo (Next.js + FastAPI) running via Docker Compose
- Auth (magic‑link), seeded demo org/users/vendors/invoices, and a dashboard with basic charts
- An ingestion → extraction → anomaly pipeline with SSE toasts + Slack webhook alerts
- CI (GitHub Actions) and a short Loom‑style demo script

---

## 1) Prerequisites (accounts, installs, access)

### Accounts & keys

- GitHub account (for repo + Actions)
- AWS account **or** local MinIO for S3‑compatible storage
- Slack workspace **and** an Incoming Webhook (for alerts)
  - **Create the webhook**
    1. Open your Slack workspace.
    2. Click workspace name → **Settings & administration** → **Manage apps**.
    3. In the Apps Directory, search **Incoming Webhooks** → **Add**.
    4. Pick a channel for alerts → **Allow**.
    5. Copy the generated **Webhook URL** (looks like `https://hooks.slack.com/services/T...`).
    6. Put it in your local secrets file `.env.local` as `SLACK_WEBHOOK_URL` (never commit it).
- Email provider for magic‑link auth (pick one):
  - **Production**: Resend / SendGrid (requires API key and verified sender domain)
  - **Development**: MailHog via Docker (captures emails at `http://localhost:8025`)
- Optional (later): OpenAI/Claude/Gemini key for LLM extraction; AWS Textract key if using managed OCR

#### Quick setup — email providers

**Option A — Resend (prod)**

1. Create account and API key; verify a domain (add DNS records). Use sender like `no-reply@yourdomain.com`.
2. Add to `.env.local`:
   ```
   RESEND_API_KEY=xxxxxxxx
   EMAIL_FROM=no-reply@yourdomain.com
   EMAIL_SERVER=smtp://smtp.resend.com:587
   EMAIL_USER=resend
   EMAIL_PASSWORD=${RESEND_API_KEY}
   ```

**Option B — SendGrid (prod)**

1. Create API key; verify a sender or domain.
2. Add to `.env.local`:
   ```
   SENDGRID_API_KEY=xxxxxxxx
   EMAIL_FROM=no-reply@yourdomain.com
   EMAIL_SERVER=smtp://smtp.sendgrid.net:587
   EMAIL_USER=apikey
   EMAIL_PASSWORD=${SENDGRID_API_KEY}
   ```

**Option C — MailHog (dev)**

1. Docker Compose will run MailHog automatically.
2. Add to `.env.local`:
   ```
   EMAIL_SERVER=smtp://mailhog:1025
   EMAIL_FROM=dev@procuresight.local
   MAILHOG_UI=http://localhost:8025
   ```

**NextAuth Email provider (example)**

```ts
// apps/web/auth/email.ts
import EmailProvider from "next-auth/providers/email";

export const emailProvider = EmailProvider({
  server: process.env.EMAIL_SERVER,
  from: process.env.EMAIL_FROM,
});
```

### Local tools

- Docker Desktop (latest) and docker‑compose v2\
  **Check:** `docker --version` and `docker compose version`
- Node.js LTS (≥ 20) + pnpm or npm\
  **Check:** `node -v` and `npm -v` (or `pnpm -v`)
- Python 3.11+ + uv/poetry **or** pip + venv\
  **Check:** `python3 --version` and either `uv --version` / `poetry --version` / `pip --version`
- Make (macOS already has it)\
  **Check:** `make --version`
- psql (PostgreSQL client)\
  **Check:** `psql --version`

**All‑in‑one prerequisite check (optional)**

```bash
set -e; \
  echo "Docker: $(docker --version)"; \
  echo "Compose: $(docker compose version)"; \
  echo "Node: $(node -v)"; \
  echo "npm: $(npm -v 2>/dev/null || true)"; \
  echo "pnpm: $(pnpm -v 2>/dev/null || true)"; \
  echo "Python: $(python3 --version 2>&1)"; \
  echo "pip: $(pip --version 2>/dev/null || true)"; \
  echo "uv: $(uv --version 2>/dev/null || true)"; \
  echo "poetry: $(poetry --version 2>/dev/null || true)"; \
  echo "make: $(make --version | head -1)"; \
  echo "psql: $(psql --version 2>/dev/null || true)";
```

### Seed & sample data

#### What to gather (targets)

- **Invoices (structured)**: 5–10 in **CSV** or **JSON** (same columns across files)
- **Invoices (unstructured PDFs)**: 5–10 mixed (image‑only + text‑based)
- **Contracts (PDFs)**: 2–3 short service/PO/terms templates
- **Data dictionary**: one markdown file describing columns, types, units, examples

#### Fastest way to get everything

1. **Structured invoices (CSV/JSON)**: create a small spreadsheet (Google Sheets/Excel → CSV) **or** use a mock data generator.
2. **PDF invoices**: export 4–6 via any invoice generator; also print a couple CSV invoices to PDF (text‑based) and **scan a few** to create image‑only PDFs (for OCR).
3. **Contracts**: download 2–3 generic templates (service agreement, purchase agreement) and export as PDF.

#### Synthetic data (scripted)

- Use `scripts/make_fake_invoices.py` (in repo) powered by **faker** to emit CSV + JSON, and (optionally) PDFs.
- Example CLI:
  ```bash
  python scripts/make_fake_invoices.py \
    --csv data/samples/invoices_csv/ \
    --json data/samples/invoices_json/ \
    --pdf data/samples/invoices_pdf/ \
    --contracts data/samples/contracts_pdf/ \
    --n 12
  ```
- Edge cases included: duplicate `invoice_no`, currency mix (USD/EUR/JPY), negative line (credit), rounding quirks, long invoices.

#### Suggested folder layout

```
data/
└─ samples/
   ├─ invoices_csv/     # structured
   ├─ invoices_json/    # structured
   ├─ invoices_pdf/     # unstructured (text + image)
   └─ contracts_pdf/    # contract templates
```

#### Minimal data dictionary (drop in `data/samples/README.md`)

```
# Data Dictionary (v0)

## invoices_csv/*.csv
- invoice_no (string) – unique per vendor; ex: INV-1042
- vendor (string) – supplier name; ex: Apex Office Supply
- date (date, ISO) – ex: 2025-09-01
- currency (string, ISO 4217) – ex: USD
- subtotal (decimal) – ex: 1200.00
- tax (decimal) – ex: 96.00
- total (decimal) – ex: 1296.00  (≈ subtotal + tax)

## invoice_lines (embedded in JSON or separate CSV)
- sku (string) – ex: PPR-A4-500
- desc (string) – ex: Copy Paper A4 500 sheets
- qty (number) – ex: 10
- unit_price (decimal) – ex: 5.99
- line_total (decimal) – ex: 59.90  (≈ qty * unit_price)
```

#### Quality checklist (helps the pipeline)
- Consistent columns across CSVs; dates are ISO (YYYY-MM-DD); currency is ISO 4217.
- Totals roughly match: `abs(subtotal + tax - total) <= 0.02`.
- Include a few edge cases: duplicate `invoice_no`, credit/negative lines, long invoices.
- PDFs mix text-based and image-only (for later OCR).

#### How to load into the app

**Follow this exact order (matches what we just did):**

1) **Start infra (Postgres + MinIO)**
   ```bash
   make up
   # equivalent: docker compose up -d db minio
   ```
   - MinIO console: http://localhost:9001 (minioadmin / minioadmin)

2) **Host-side env for scripts** (use localhost, because the scripts run on your host)
   Create `.env.local` in the repo root:
   ```
   DATABASE_URL=postgresql://procure:procure@localhost:5432/procuresight
   S3_ENDPOINT=http://localhost:9000
   S3_ACCESS_KEY=minioadmin
   S3_SECRET_KEY=minioadmin
   S3_BUCKET=procuresight
   ```

3) **Create schema**
   ```bash
   make seed
   ```

4) **Upload & register** (walks `data/samples/**`, uploads to MinIO, inserts into `raw_docs`)
   ```bash
   make load-samples
   ```
   Example success: `[ok] uploaded N files and registered rows in raw_docs`.

**Verify**
- MinIO bucket `procuresight` contains `samples/...` objects (UI on :9001).
- DB has rows:
  ```bash
  psql "$DATABASE_URL" -c "select id, filename, s3_uri from raw_docs limit 10;"
  ```

**Troubleshooting**
- `no configuration file provided`: run from repo root (where `docker-compose.yml` lives).
- `make: No rule to make target 'up'`: run `cd <repo-root>` or `make -C .. up`.
- Connection errors to MinIO from host: use `S3_ENDPOINT=http://localhost:9000` (use `minio:9000` **only inside containers**).

### Security baseline

**Next step (do this now):**

- **Create `.env.example`** (committed, no secrets) in the repo root with documented keys used by web/api and scripts. Example:
  ```
  # DB (container-to-container; used by services when we add them)
  POSTGRES_HOST=db
  POSTGRES_USER=procure
  POSTGRES_PASSWORD=procure
  POSTGRES_DB=procuresight
  DATABASE_URL=postgresql://procure:procure@db:5432/procuresight
  
  # Storage (container-to-container)
  S3_ENDPOINT=http://minio:9000
  S3_ACCESS_KEY=minioadmin
  S3_SECRET_KEY=minioadmin
  S3_BUCKET=procuresight
  
  # Email (dev)
  EMAIL_SERVER=smtp://mailhog:1025
  EMAIL_FROM=dev@procuresight.local
  
  # Alerts
  SLACK_WEBHOOK_URL=
  ```
  > Note: your **host-run scripts** use `.env.local` with `localhost` endpoints (already created above). Services in Docker will use the `db`/`minio` hostnames from `.env.example`.

- **Keep secrets out of git**
  - Ensure `.gitignore` contains:
    ```
    .env.local
    venv/
    __pycache__/
    *.pyc
    data/samples/**
    ```

- **Tenancy decision placeholder**
  - We'll start single-tenant for dev; add Row-Level Security (RLS) per org in Week 2.

- *(Optional but recommended)* Add basic controls
  - `pre-commit` hooks for formatting/lint.
  - `gitleaks` to scan for secrets before push.

---

## 2) Repo scaffold (folders, configs, scripts)

```
procuresight/
├─ apps/
│  ├─ web/                  # Next.js (TS) app
│  └─ api/                  # FastAPI service
├─ packages/
│  ├─ ui/                   # (optional) shared UI components
│  └─ config/               # eslint, tsconfig, prettier, etc.
├─ infra/
│  ├─ docker/               # Dockerfiles, compose files
│  ├─ db/                   # migrations, seed SQL, dbt (later)
│  └─ terraform/            # (optional) IaC for cloud
├─ scripts/                 # dev scripts (seed, load samples)
├─ .github/workflows/       # CI pipelines
├─ .env.example             # documented env vars
├─ Makefile                 # common commands
└─ README.md
```

#### Current repo state (v0 now)

```
ProcureSight/
├─ data/samples/
├─ scripts/
│  ├─ make_fake_invoices.py
│  ├─ seed.py
│  └─ load_samples.py
├─ docker-compose.yml
├─ Makefile
├─ .env.local            # host-side env used by scripts
└─ venv/                 # local virtualenv (ignored)
```

### Docker Compose (services)

**Now (running today):**
- `db`: Postgres 15 (exposed on `localhost:5432`)
- `minio`: S3-compatible storage (API on `localhost:9000`, console on `localhost:9001`)

**Planned (add in Week 1 tasks):**
- `web`: Next.js + Auth.js (magic-link) on `localhost:3000`
- `api`: FastAPI service on `localhost:8000`
- `mailhog`: local email capture for auth (UI on `localhost:8025`)

### Example `.env.example`

```
# Web
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=<generate>
EMAIL_SERVER=smtp://mailhog:1025
EMAIL_FROM=dev@procuresight.local
# RESEND_API_KEY=
# SENDGRID_API_KEY=

# API
API_PORT=8000
OPENAI_API_KEY=
AWS_REGION=

# DB
POSTGRES_HOST=db
POSTGRES_USER=procure
POSTGRES_PASSWORD=procure
POSTGRES_DB=procuresight
DATABASE_URL=postgresql://procure:procure@db:5432/procuresight

# Storage (MinIO)
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=procuresight

# Alerts
SLACK_WEBHOOK_URL=
```

### Makefile conveniences

**Current (v0 now)**
```
up:        ## start db + minio
	docker compose up -d db minio

down:      ## stop all
	docker compose down

ps:
	docker compose ps

dbshell:   ## psql into DB from host
	psql "postgresql://procure:procure@localhost:5432/procuresight"

seed:      ## create schema
	python scripts/seed.py

load-samples: ## upload sample files to MinIO + register in raw_docs
	python scripts/load_samples.py data/samples
```

**Planned (when apps are added)**
```
setup:        ## install deps for web/api
	cd apps/web && pnpm i
	cd apps/api && uv sync || pip install -r requirements.txt

dev:          ## run full stack
	docker compose up --build
```

### Coding standards & workflow

- Conventional commits; PR template; branch naming: `feat/…`, `fix/…`
- Lint/format: ESLint + Prettier (web), Ruff/Black (api)
- Type‑first contracts: OpenAPI schema → client SDK (or tRPC alt)
- Test: Vitest/Playwright (web), Pytest (api)

### Slack webhook — quick test

Use either curl, Node, or Python to confirm your webhook works **before** wiring it into the app.

**curl**

```bash
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"✅ ProcureSight webhook test from local dev"}' \
  "$SLACK_WEBHOOK_URL"
```

**Node (fetch)**

```js
await fetch(process.env.SLACK_WEBHOOK_URL, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text: '✅ ProcureSight webhook test from Node' })
});
```

**Python (requests)**

```py
import os, requests
requests.post(os.environ['SLACK_WEBHOOK_URL'], json={"text":"✅ ProcureSight webhook test from Python"})
```

---

## 3) Data model (v0)

**Tables**

- `orgs(id, name)`
- `users(id, org_id, email, role)`
- `vendors(id, org_id, name)`
- `raw_docs(id, org_id, s3_key, filename, mime, bytes, uploaded_by, uploaded_at)`
- `extractions(id, raw_doc_id, status, confidence, payload_json, created_at)`
- `invoices(id, org_id, vendor_id, invoice_no, date, currency, subtotal, tax, total)`
- `invoice_lines(id, invoice_id, sku, desc, qty, unit_price, line_total)`
- `alerts(id, org_id, type, severity, message, meta_json, created_at)`
- `audit_log(id, org_id, actor_id, action, target, meta_json, at)`

**Indexes/constraints**

- Unique `(org_id, vendor_id, invoice_no)` to detect duplicates
- Partial index on `alerts(severity)` for quick unread counts

**Row‑level security (RLS)**

- Enable RLS; policies to enforce `org_id = current_setting('app.org_id')::uuid`

---

## 4) Ingestion pipeline (v0 → v1)

- **Upload UI**: drag‑and‑drop → POST `/api/ingest`
- **Storage**: stream to S3/MinIO; store metadata in `raw_docs`
- **Event**: enqueue extraction job (simple queue or Temporal/Airflow later)
- **SSE toast**: client subscribes to `/events` for "processed" updates

**v1 Enhancements**

- Virus scan stub (hash check)
- Idempotency keys (same file upload doesn’t duplicate work)
- Backfill script: iterate `raw_docs` and re‑run extraction

---

## 5) Extraction (structured + unstructured)

- **Structured (CSV/JSON)**: pydantic models → write straight into `invoices`/`invoice_lines`
- **Unstructured (PDF)**: OCR (Tesseract or Textract) → text blocks → LLM prompt for entity extraction
- **Validation**: schema + totals reconciliation (sum(lines) ≈ total ± tolerance)
- **Confidence**: per‑field confidence; low confidence → review queue UI

**LLM prompt template (sketch)**

```
Extract: vendor, invoice_no, date, currency, line_items[{desc, qty, unit_price, line_total}].
Return strict JSON matching this schema: …
```

---

## 6) Anomaly detection (v1)

- **Features**: unit price deltas vs vendor median, duplicates (invoice\_no, total), sudden volume spikes
- **Model**: Isolation Forest (scikit‑learn) on engineered features; simple thresholds as baseline
- **Alerts**: write to `alerts` and push to Slack via webhook
- **Dashboard**: "Top anomalies" table with acknowledge/dismiss

---

## 7) Web app (MVP)

- **Auth**: Auth.js magic link (MailHog in dev)
- **Pages**: Login, Uploads, Invoices (table), Vendors, Alerts, Dashboard
- **Charts**: Vendor spend by month (bar), anomalies over time (line)
- **Real‑time**: SSE for new file processed + new alert

---

## 8) Orchestration (week 2)

- Choose **Temporal** or **Airflow**:
  - DAG: `ingest → extract → validate → score → notify`
  - Retries with exponential backoff; dead‑letter queue for failures
  - Idempotent activity design (use `raw_doc_id` as key)

---

## 9) CI/CD

- **GitHub Actions**:
  - Lint/test on PR
  - Build Docker images
  - Spin up services and run an end‑to‑end smoke test (upload → alert)
- (Optional) Render/Zeet/Fly.io preview deployments for the web app

---

## 10) Demo artifacts

- **Screenshots**: upload page, dashboard, alert toast, Slack message
- **Loom script** (90 sec): problem → upload → auto extraction → anomaly → alert
- **README**: quickstart, env vars, data model diagram, architectural sketch

---

## 11) Two‑week plan (expanded tasks)

### Week 1 — Usable MVP

**Day 1** — Monorepo & Compose

- Init repo with `apps/web` (Next.js/TS) and `apps/api` (FastAPI)
- Add Compose for web/api/db/minio/mailhog; verify all containers start
- Create `.env.example`; document run steps in README

**Day 2** — Auth + DB + Seeds

- Add Auth.js magic‑link using MailHog SMTP
- Create migration for base tables (orgs, users, vendors, raw\_docs, invoices, invoice\_lines, alerts, audit\_log)
- Write `scripts/seed.py` to insert demo org/users/vendors

**Day 3** — Ingestion v0

- Implement web upload → POST `/api/ingest`
- Stream file to MinIO; insert `raw_docs` row
- Fire SSE event: `upload_received`

**Day 4** — Extraction v0

- If CSV/JSON: parse with pydantic → write invoices/lines
- If PDF: stub OCR (return TODO) + store text blob in `extractions`
- Recompute vendor totals for dashboard cache table (materialized view optional)

**Day 5** — Dashboard v0 + CI

- Build dashboard page: vendor spend (bar), recent uploads, placeholder anomalies
- Add SSE toasts for `doc_processed`
- Add GitHub Actions (lint, test, build images); capture screenshots

**Deliverables**

- Running stack via `docker compose up`
- Auth works; can upload CSV invoice; dashboard shows spend
- CI passes; README with screenshots

### Week 2 — Looks like a startup MVP

**Day 6–7** — LLM extraction

- Add OCR (Tesseract locally); extract text blocks
- Prompt LLM to produce JSON entities; map to schema
- Compute field‑level confidence; items < threshold go to review queue UI

**Day 8** — Anomaly v1 + Alerts

- Engineer features; train Isolation Forest baseline
- Show "Top anomalies" in UI; push Slack webhook

**Day 9** — Orchestration

- Introduce Temporal/Airflow DAG with retries + idempotency
- Add backfill command over `raw_docs`

**Day 10** — Security & Polish

- Enable RLS policies per org; add audit logging hooks
- Record 90‑sec demo; finalize README, arch diagram, and "pilot results" notes

**Stretch (later)**

- pgvector + RAG with clause‑level citations
- dbt transforms & D3 sankey (vendor → category flows)
- SSO (Google) and role‑based permissions matrix

---

## 12) Task checklists (copy/paste into issues)

-

---

## 13) Nice‑to‑have developer UX

- Dev data **factory** script to generate synthetic invoices (faker)
- Storybook for UI components
- `openapi.json` generated by FastAPI; typed client in web app
- Playwright e2e: upload → alert scenario

---

## 14) Risks & mitigations

- **OCR quality** → start with text‑based PDFs; add Tesseract later
- **LLM hallucinations** → strict JSON schema; validate totals; low‑confidence queue
- **Data privacy** → PII masking; delete raw files on request; audit logging
- **Time budget** → keep Week 1 to structured CSV path; bring PDFs in Week 2

---

## 15) Quick start (TL;DR)

1. Install Docker; clone repo; `cp .env.example .env`
2. `make dev` → web on :3000, api on :8000
3. `make seed` → org/users/vendors
4. Upload `samples/invoice.csv` → see dashboard chart + toast
5. (Optional) set `SLACK_WEBHOOK_URL` → receive anomaly alert

