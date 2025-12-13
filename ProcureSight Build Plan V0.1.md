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


### Create `docker-compose.yml` and `Makefile` (required before loading)

We use Compose to run **Postgres** and **MinIO** locally, and a Makefile for repeatable commands. Create these two files at the **repo root** before running the load step.

#### `docker-compose.yml`

> Note: Compose v2 treats the top-level `version:` field as obsolete. If you see a warning about `version` you can safely remove that line.

```yaml
services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: procuresight
      POSTGRES_USER: procure
      POSTGRES_PASSWORD: procure
    ports:
      - "5432:5432"
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U procure -d procuresight"]
      interval: 5s
      retries: 20

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"   # S3 API
      - "9001:9001"   # Web console
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/ready"]
      interval: 5s
      retries: 30

volumes:
  db_data:
  minio_data:
```

#### `Makefile`

Place this `Makefile` at the repo root. Each recipe line begins with a **TAB**.

```make
.PHONY: up down ps dbshell seed load-samples

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

**Usage**
```bash
make up         # starts Postgres + MinIO
make seed       # creates tables/fixtures
make load-samples
```

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

# API
API_PORT=8000
OPENAI_API_KEY=
AWS_REGION=

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

### Architecture recap (so far)

What’s running and how the pieces connect — quick mental model:

- **apps/api/** → FastAPI backend (Python). Exposes endpoints (e.g., `/vendors`) and publishes the OpenAPI spec at `/openapi.json`.
- **packages/types/** → Auto‑generated TypeScript definitions (`api.d.ts`) from the OpenAPI spec. Keeps frontend and backend in sync.
- **packages/client/** → Tiny TypeScript SDK that wraps `fetch` using those types (via `openapi-fetch`). Any app can import this (web/admin later).
- **apps/web/** → Next.js frontend (TypeScript/React). Uses the client SDK to call the API and render UI. *(Scaffolded next in the plan.)*

**Data flow:**
```
FastAPI (Python)
   ↓ generates
OpenAPI JSON
   ↓ generates
packages/types/api.d.ts (TS types)
   ↓ wrapped by
packages/client (typed SDK)
   ↓ used by
apps/web (Next.js UI)
```

**Dev environment reminders:**
- **Host vs. containers:** use `localhost` in `.env.local` for host‑run scripts; use `db`/`minio` inside containers (`.env.example`).
- **Type gen loop:** `make openapi` → `make types` (refresh spec, then TS types). You can also generate directly from the running server URL later.
- **Why a separate client package?** Centralizes API setup + types once, so multiple apps can reuse it without duplicating code.

---

## 3) Data model (v0)

> Goal: clean separation of **files** (MinIO/S3) and **facts** (Postgres), safe multi-tenant by default, and easy to evolve.

### 3.1 Why this shape?
- **Multi-tenant from day 0**: every business table has `org_id`; RLS enforces org isolation in the DB.
- **Files vs. structured data**: PDFs live in object storage; Postgres holds pointers + invoice facts for querying.
- **Staging → authoritative**: `extractions` stores raw JSON from OCR/LLM; `invoices`/`invoice_lines` store validated facts.
- **Auditability & monitoring**: `audit_log` for who/what/when; `alerts` for anomalies (duplicates, mismatches, late, etc.).

### 3.2 Entity map (quick ER sketch)
```
orgs 1─* users
  │
  ├─* vendors
  │     └─* invoices ──* invoice_lines
  │            ▲   \
  │            │    └─(optional) raw_docs (file pointer)
  │            │                     │
  │            │                     └─* extractions (JSON results per file)
  └─* alerts, audit_log
```

### 3.3 Tables (v0)
- `orgs(id, name, created_at)`
- `users(id, org_id, email, role, created_at)`
- `vendors(id, org_id, name, created_at)`
- `raw_docs(id, org_id, s3_key, filename, mime, bytes, uploaded_by, uploaded_at)`
- `extractions(id, raw_doc_id, status, confidence, payload_json, created_at)`
- `invoices(id, org_id, vendor_id, invoice_no, invoice_date, due_date, currency, subtotal, tax, total, status, raw_doc_id, created_at)`
- `invoice_lines(id, invoice_id, sku, desc, qty, unit_price, line_total)`
- `alerts(id, org_id, type, severity, message, meta_json, created_at, resolved)`
- `audit_log(id, org_id, actor_id, action, target, meta_json, at)`

**Keys & types (high-level):**
- UUID primary keys for most entities; `raw_docs.id` is `BIGSERIAL` (handy for ingestion logs).
- Money: `NUMERIC(18,2)`; quantities/price: `NUMERIC(18,4)`.

### 3.4 Constraints & indexes
- **Duplicate protection**: `UNIQUE (org_id, vendor_id, invoice_no)` on `invoices` (same invoice number can exist across vendors or orgs, but not within the same pair).
- **Alert performance**: partial index `CREATE INDEX ... ON alerts(severity) WHERE resolved = FALSE` for fast “unresolved by severity”.
- **FK deletes**:
  - `... ON DELETE CASCADE` for org-scoped children (users/vendors/raw_docs/invoices/invoice_lines/alerts/audit_log).
  - `invoices.raw_doc_id ... ON DELETE SET NULL` so history remains if a file is removed.

### 3.5 Row-level security (RLS)
**What it is:** DB-enforced row filters. We enable RLS on org-scoped tables and add policies that compare the row’s `org_id` to the current session’s org.

**How it works here:**
- App (or `psql`) sets the org context per request/session:
  ```sql
  SET app.org_id = '<org-uuid>';  -- used by policies
  ```
- Example SELECT policy (conceptual):
  ```sql
  -- Only see rows in your org
  CREATE POLICY org_select_invoices ON invoices
    FOR SELECT USING (org_id = current_setting('app.org_id', true)::uuid);
  ```
- Example INSERT policy (conceptual):
  ```sql
  -- Only insert rows for your org
  CREATE POLICY org_insert_invoices ON invoices
    FOR INSERT WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);
  ```
- For children lacking `org_id` (e.g., `invoice_lines`), the policy checks via the parent (`EXISTS (SELECT 1 FROM invoices ...)`).

> **Why RLS now?** It prevents the classic “forgot the WHERE org_id = ?” bug and keeps multi-tenant safety **in the database**, not just in app code.

### 3.6 What creates this schema?
- `scripts/seed.py` executes SQL DDL to create tables, constraints, indexes, and RLS policies. It’s **idempotent** (safe to re-run).
- Run order during dev:
  ```bash
  make up    # start Postgres + MinIO
  make seed  # create/verify schema
  ```

### 3.7 Verify quickly in psql
```sql
-- show tables
\dt

-- invoices unique constraint exists
\d invoices  -- look for "UNIQUE (org_id, vendor_id, invoice_no)"

-- policies are present
SELECT policyname, tablename
FROM pg_policies
WHERE tablename IN ('users','vendors','raw_docs','extractions','invoices','invoice_lines','alerts','audit_log')
ORDER BY tablename, policyname;
```

### 3.8 Example queries you’ll actually run
```sql
-- newest files you uploaded (metadata only)
SELECT id, s3_key, filename, mime, bytes, uploaded_at
FROM raw_docs
ORDER BY uploaded_at DESC
LIMIT 10;

-- latest invoices with vendor and totals
SELECT v.name AS vendor, i.invoice_no, i.invoice_date, i.currency, i.total
FROM invoices i
JOIN vendors v ON v.id = i.vendor_id
ORDER BY i.invoice_date DESC
LIMIT 20;

-- invoice + lines (detail view)
SELECT i.invoice_no, il.sku, il."desc", il.qty, il.unit_price, il.line_total
FROM invoice_lines il
JOIN invoices i ON i.id = il.invoice_id
WHERE i.invoice_no = 'INV-12345';
```

### 3.9 FAQ
- **Is MinIO a database?** No. It stores the **files** (PDF bytes). Postgres stores **metadata + parsed facts**. They’re linked by `raw_docs.s3_key`.
- **Where do date/currency/total live?** In `invoices` (header) and `invoice_lines` (details). `raw_docs` knows file info only.
- **Can we switch to AWS S3 later?** Yes. We keep to the S3 API and store `bucket + s3_key` in DB; switching is mostly env + data sync.



---

## 4) Ingestion pipeline (v0 → v1)

> Turn uploads into durable records: **UI → /api/ingest → MinIO → raw_docs → events (next).**

### Goal
Turn uploads into durable, queryable records and notify clients in real time, with idempotent behavior for repeated uploads.

**Checklist**
- [x] Can upload from a client and receive `200 OK` with a `raw_doc_id`.
- [x] Object appears in MinIO with the expected key; a new `raw_docs` row points to it.
- [x] An SSE message arrives to clients listening on `/events` (e.g., `upload_received` with `raw_doc_id`).
- [x] Re-running the same upload (exact same bytes) is blocked/marked as duplicate using SHA‑256; returns the original `raw_doc_id`/`s3_key` with `"duplicate": true` (no new S3 object, no new DB row).

---

### Endpoint contract (v0)
- **POST** `/api/ingest`
  - **Body**: `multipart/form-data`
    - `file` (required): the file to upload
    - `org_id` (optional): overrides default org from env
  - **Response 200**:
    ```json
        { "raw_doc_id": <int>, "s3_key": "org/<org-uuid>/uploads/<uuid>/<filename>", "duplicate": <bool> }
    ```
  - When `"duplicate": true`, the response refers to an existing row/object; the server skips re-uploading to S3 and skips inserting a new `raw_docs` row.
- **Side effects**
  - **S3/MinIO**: store bytes under `org/<org_id>/uploads/<uuid>/<filename>`
  - **Postgres** (`raw_docs`): insert `(org_id, s3_key, filename, mime, bytes, uploaded_by)`
  - **RLS context**: API sets `SET LOCAL app.org_id = :org_id` and, if present, `SET LOCAL app.actor_id = :uploaded_by` prior to `INSERT` so policies pass.
  - **Idempotency**: compute `sha256` of the uploaded bytes; if `(org_id, sha256)` already exists in `raw_docs`, short-circuit and return the existing row with `"duplicate": true`.

### Environment & bootstrap
- `.env.local` (host‑run) must include:
  ```
  DATABASE_URL=postgresql://procure:procure@localhost:5432/procuresight
  S3_ENDPOINT=http://localhost:9000
  S3_ACCESS_KEY=minioadmin
  S3_SECRET_KEY=minioadmin
  S3_BUCKET=procuresight
  ORG_ID=<uuid>          # from seed output
  UPLOADER_ID=<uuid>     # from seed output (optional if schema allows NULL)
  ```
  **No angle brackets** around actual values (write bare UUIDs).
- `scripts/seed.py` bootstraps **Demo Org** and **Demo Uploader** idempotently and prints:
  ```
  DEMO_ORG_ID=<uuid>
  DEMO_UPLOADER_ID=<uuid>
  ```
- MinIO bucket **must exist** (name = `S3_BUCKET`). Create via console (`http://localhost:9001`) or:
  ```
  export AWS_ACCESS_KEY_ID=minioadmin
  export AWS_SECRET_ACCESS_KEY=minioadmin
  aws --endpoint-url http://localhost:9000 s3 mb s3://procuresight
  ```

### Verification recipe (repeatable)
1. **Health**
   ```
   curl -s http://localhost:8000/health | jq
   # → {"ok":true,"db":true,"s3":true}
   ```
2. **Upload**
   ```
   curl -s -X POST http://localhost:8000/api/ingest \
     -F "file=@data/samples/invoices_pdf/INV-01-202509-0001.pdf" | jq
   # → { "raw_doc_id": N, "s3_key": "org/<ORG_ID>/uploads/<uuid>/INV-01-202509-0001.pdf" }
   ```
3. **DB row (RLS aware)**
   ```sql
   SET app.org_id = '<ORG_ID>';
   SELECT id, filename, mime, bytes, s3_key
   FROM raw_docs ORDER BY id DESC LIMIT 5;
   ```
4. **S3 object**
   ```
   aws --endpoint-url http://localhost:9000 s3 ls s3://procuresight/org/<ORG_ID>/uploads/ --recursive
   ```

### Real-time updates via SSE (what & why)

**What is SSE?** Server‑Sent Events keep a single HTTP connection open so the API can *push* small JSON messages to the browser, instead of the UI *polling* every few seconds. This makes the app feel instant (upload received, extraction done, alert created).

**Why here?** Right after an upload succeeds, the API can notify the UI immediately:
- `upload_received` (v0 now) → show a toast and update “Recent uploads”
- `doc_processed` (v1) → extraction finished, link to parsed invoice
- `alert_created` (v1) → anomaly detected, link to alert

**Endpoint (dev):**  
- **GET** `/events` → `text/event-stream` (SSE)
- Sends keep‑alive `: ping` comments every 15s to prevent idle timeouts.

**Event format (each line block ends with a blank line):**
```
data: {"type":"upload_received","raw_doc_id":123,"s3_key":"org/<ORG_ID>/uploads/<uuid>/<filename>"}

```

**Minimal browser client (works in Next.js/vanilla):**
```ts
const es = new EventSource("http://localhost:8000/events");
es.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.type === "upload_received") {
    // show toast, refresh uploads table, etc.
    console.log("Upload received:", msg.raw_doc_id);
  }
};
```

**Flow sketch**
```
Client ──POST /api/ingest──▶ API ──put_object──▶ MinIO
          ▲                         │
          │                         └─INSERT raw_docs (RLS set)
          └───────◀──SSE /events──── broadcast {"type":"upload_received", raw_doc_id}
```

**Future evolution (beyond in‑process SSE)**

- **Near‑term (v1.5): Redis Pub/Sub (same client contract).** Replace the in‑process `SUBSCRIBERS` set with Redis channels.  
  - Producer: `/api/ingest` publishes `upload_received` to `events:<org_id>`.  
  - Consumer: `/events` subscribes to `events:<org_id>` and streams messages.  
  - Why: supports multiple API instances with minimal code change. `/events` stays the same for the web app.
- **Mid‑term (v2): Separate “work queue” from “notify bus.”**  
  - **Durable jobs** (retries/DLQ): Celery/RQ/Arq or Redis Streams for extraction, validation, etc.  
  - **Ephemeral fan‑out** (UI toasts): Redis Pub/Sub for `upload_received`, `doc_processed`, `alert_created`.
- **Long‑term (v3): Durable event log.** Use Kafka/Pulsar/NATS JetStream for organization‑wide events and replay/audit. Keep `/events` as a thin gateway (SSE/WebSocket) that reads from the durable log.
- **Scale considerations:**  
  - AuthN on `/events` (JWT) + org‑scoped channels.  
  - Per‑client buffer cap to handle slow consumers.  
  - Metrics: connected clients, publish latency, dropped messages.

### Troubleshooting
- **`invalid input syntax for type uuid: "<…>"`** → `.env.local` contains angle brackets; use bare UUIDs.
- **`NoSuchBucket`** on upload → create the bucket named in `S3_BUCKET` first.
- **Health `db:false` or `s3:false`** → verify Docker services (`make up`) and env values.
- **Inserted file not visible in `SELECT`** → RLS requires `SET app.org_id = '<ORG_ID>'` for your psql session.
- **Writes blocked by RLS** → ensure API sets `SET LOCAL app.org_id` (and `app.actor_id`) before `INSERT` (already implemented).
- **DB vs API mismatch** → confirm both use the same `DATABASE_URL` (host `localhost`, not `db`, for host‑run API).

### v1 Enhancements (next)
- **Idempotency**: compute `sha256` on upload; if `(org_id, sha256)` exists in `raw_docs`, return existing `raw_doc_id` (no duplicate work).
- **SSE**: broadcast `upload_received` (v0) and `doc_processed` (post‑extraction) on `/events` for the UI.
- **Queue**: enqueue extraction job (Celery/RQ/Temporal placeholder).
- **Virus scan stub**: blocklisted hash list before persisting.
- **Backfill**: CLI to iterate `raw_docs` and re‑run extraction.
- **Orphan cleanup**: if S3 upload succeeds but DB insert fails, mark/delete orphan objects (dev utility).

---

## 5) Extraction (structured + unstructured)

> Current scope: structured CSV/JSON + text-based PDFs using LLM extraction. OCR for scanned/image PDFs will be added later.

- **Structured (CSV/JSON)**: `Invoice` / `InvoiceLine` Pydantic models → validation → write into `invoices` / `invoice_lines`.
- **Validation**: schema checks + business rules (per-line math, subtotal vs. sum of lines, total vs. subtotal + tax, with rounding tolerance).
- **Confidence**: invoice-level and per-field confidence scores computed from validation results; low confidence is flagged for review in the UI later.
- **Unstructured (text-based PDF)**: extract text from PDF pages (via `pdfplumber`) → LLM prompt for entity extraction into `Invoice`-shaped JSON. OCR for image-only/scanned PDFs will be added in a future iteration.

**Endpoints (v0.1)**

- `POST /extract/structured`
  - Accepts **JSON** or **CSV** uploads.
  - JSON path: expects an `Invoice`-shaped document, validates it, computes confidence, and upserts into `invoices` / `invoice_lines`.
  - CSV path: parses rows into `Invoice` objects, runs the same validation + confidence logic, and persists multiple invoices in one call.

- `POST /extract/unstructured`
  - Accepts **text-based PDF** uploads.
  - Pipeline: PDF bytes → text extraction (`pdfplumber`) → LLM extraction to `Invoice` JSON → validation + confidence → write to `invoices` / `invoice_lines`.
  - Returns the new `invoice_id` plus warnings, confidence scores, and a `needs_review` flag derived from validation.

**LLM prompt template (sketch)**

```
Extract: vendor, invoice_no, invoice_date, due_date, currency,
subtotal, tax, total, and line items [{ sku, desc, qty, unit_price, line_total }].
Return strict JSON matching this schema.
```

### Potential Improvements (v1.5+)

- **Schema validation + versioning** — Store each extraction with a version tag (`ocr_engine`, `prompt_hash`, `model_name`) and validate LLM output with Pydantic before inserting into `invoices`.
- **Vendor resolution** — Use fuzzy/canonical name mapping to ensure consistent vendor IDs (e.g., “Apex Office Supply” vs “Apex Office Supplies”).
- **Human-in-the-loop review UI** — Display PDFs side-by-side with parsed JSON for low-confidence fields; allow inline edits and save to `audit_log`.
- **Pre-checks (before extract)** — MIME/type validation, file size/page limit, virus scan, skip encrypted PDFs, and route image-only PDFs through OCR.
- **Structured data normalization** — Header aliasing, type coercion, ISO 4217 currency normalization.
- **Model/versioning detail** — Store raw OCR text and parsed JSON with extraction metadata for reproducibility.
- **LLM guardrails** — Strict JSON schema validation, deterministic prompts, and regex fallback for essential fields.
- **Retry & idempotency** — Key retries by `raw_doc_id`; retry only transient OCR/LLM errors.
- **Line-item robustness** — Multi-page table detection and rounding consistency.
- **Confidence math** — Combine OCR and heuristic confidences for better scoring.
- **Metrics & alerts** — Track extraction success rate, latency, and alert on spikes or failures.
- **Re-extract tooling** — CLI for re-running OCR/LLM on subsets of documents.
- **Privacy & cost** — Redact PII, cache OCR outputs, and chunk long docs for efficiency.

---

## 6) Anomaly detection (v1)

- **Features**: unit price deltas vs vendor median, duplicates (invoice\_no, total), sudden volume spikes
- **Model**: Isolation Forest (scikit‑learn) on engineered features; simple thresholds as baseline
- **Alerts**: write to `alerts` and push to Slack via webhook
- **Dashboard**: "Top anomalies" table with acknowledge/dismiss

1. **Alerts data model + migrations**
   - Ensure the `alerts` table exists with fields like: `id, org_id, invoice_id, vendor_id, type, severity, score, message, meta_json, status, created_at, acknowledged_at, acknowledged_by`.
   - Add indexes for unresolved alerts and `(org_id, created_at)` to support dashboard queries.

2. **Feature engineering on invoices**
   - Compute per-vendor unit price stats (median/mean) per SKU/description.
   - Compute historical spend and invoice counts per vendor (e.g., last 30–90 days).
   - Store these aggregates in helper views or tables that scoring functions can query efficiently.

3. **Rule-based anomaly checks (baseline scoring)**
   - Flag large unit price deltas vs vendor median (for example, > 2–3x typical unit price).
   - Detect potential duplicates (same `vendor_id + invoice_no` and/or same `vendor_id + total`).
   - Flag sudden volume spikes where an invoice total is far above recent vendor averages.
   - Implement as a function `score_invoice(invoice_id)` that returns a list of alert candidates.

4. **Wire scoring into the pipeline / API**
   - After extraction and validation write to `invoices` / `invoice_lines`, call `score_invoice(invoice_id)`.
   - Insert the resulting alerts into `alerts`, respecting org-level RLS.
   - Optionally expose `POST /score/invoice/{invoice_id}` to manually re-score an invoice for debugging.

5. **Slack + SSE notifications**
   - On creation of new open alerts, send a Slack message via webhook summarizing vendor, invoice_no, type, severity, and a link back to the app.
   - Emit SSE `alert_created` events on `/events` so the web UI can show a toast and refresh alerts in real time.

6. **Backend APIs for alert listing & update**
   - `GET /alerts` with filters for `status`, `severity`, and pagination; always scoped to the current org.
   - `PATCH /alerts/{id}` to acknowledge or dismiss alerts (update `status`, `acknowledged_at`, and `acknowledged_by`).

7. **Dashboard "Top anomalies" table**
   - Add a "Top anomalies" section to the Dashboard page driven by the alerts API.
   - Include columns for vendor, invoice_no, type, severity/score, created_at, status, and actions (acknowledge/dismiss).
   - Use SSE to live-update the table when `alert_created` events arrive.

8. **Isolation Forest baseline (v1.1+)**
   - Train an Isolation Forest model (scikit-learn) using engineered per-invoice features (e.g., normalized unit price deviations, spend vs baseline, invoice frequency).
   - Store the continuous anomaly score in `alerts.score` or in a companion table and use it to rank alerts.
   - Keep rule-based checks as the explainable backbone and layer ML scores on top for better prioritization.
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

