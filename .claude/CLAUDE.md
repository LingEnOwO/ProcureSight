# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ProcureSight is a multi-tenant invoice processing SaaS. Users upload PDFs, CSVs, or JSON invoices; the system extracts structured data via LLM (GPT-4o), scores for anomalies, and streams real-time alerts to the browser.

## Development Commands

### Local Infrastructure

```bash
make up           # Start Postgres, MinIO, Redis, MailHog via Docker Compose
make down         # Stop all containers
make seed         # Create tables and load fixtures
make load-samples # Upload sample invoices to MinIO
```

### Backend (FastAPI)

```bash
cd apps/api
source ../../venv/bin/activate
uvicorn apps.api.main:app --reload --port 8000   # Dev server
arq apps.api.worker.settings.WorkerSettings       # Background job worker (must run separately)
pytest apps/api/tests/                            # Run all API tests
pytest apps/api/tests/test_foo.py::test_bar       # Run single test
```

### Frontend (Next.js)

```bash
pnpm install                     # Install all workspace dependencies
pnpm --filter ./apps/web dev     # Dev server at http://localhost:3000
pnpm web:test                    # Run Vitest tests
pnpm --filter ./apps/web build   # Production build
```

### Type Generation (run after changing FastAPI routes/models)

```bash
make openapi   # Regenerate openapi.json from FastAPI
make types     # Regenerate packages/types/api.d.ts from openapi.json
```

## Architecture

### Request Flow

```
Browser → Next.js (port 3000) → FastAPI (port 8000, private)
                                       ↓
                              ARQ Worker (background)
                                       ↓
                         Postgres | MinIO S3 | Redis
```

### Authentication Gateway Pattern

The Next.js app is the only entry point for users. It validates the NextAuth session and forwards identity via trusted headers (`X-Org-Id`, `X-Business-User-Id`, `X-User-Role`) to FastAPI. The backend trusts these headers without re-validating tokens — the API is not publicly exposed. Next.js API routes under `app/api/` act as a proxy.

### Multi-Tenancy (Row-Level Security)

Every org-scoped table has PostgreSQL RLS policies keyed on the `app.org_id` GUC. The backend sets this GUC at the start of each request via `db.py`. Never query org-scoped tables without setting this context variable first.

### Async Processing Pipeline

1. `POST /ingest` — file uploaded to MinIO, `raw_docs` row created, job enqueued → returns `202 + raw_doc_id`
2. ARQ worker runs `extract_document` (PDF via `pdfplumber` → GPT-4o structured output, or CSV/JSON direct parse)
3. Worker runs `score_invoice_job` — anomaly detection against `vendor_unit_price_stats` and `vendor_spend_stats` views
4. Results published to Redis pub/sub channel → streamed to browser via `GET /events` (SSE)
5. On demand: `POST /alerts/{alert_id}/explain` — RAG explanation system generates LLM-backed summaries for alerts

### RAG Explanation System

`POST /alerts/{alert_id}/explain?force=false` generates an evidence-backed explanation for any alert.

**Flow:**

1. Load alert from DB
2. Retrieve structured SQL evidence (type-specific: price history, volume history, or duplicate match fields)
3. Build a prompt combining alert metadata + evidence
4. Call GPT-4o with a JSON schema for structured output; fall back to deterministic templates if LLM is unavailable
5. Cache `explanation_text`, `explanation_json`, and `explanation_generated_at` on the alerts row; skip regeneration unless `?force=true`

**Supported alert types:**

- `unit_price_delta` — retrieves current line, historical same-vendor/SKU lines, and price stats
- `vendor_volume_spike` — retrieves current invoice, last 10 historical invoices, and baseline stats
- `duplicate_invoice` — retrieves both invoices and the matched fields

**LLM output schema** (enforced via JSON mode):

```json
{
  "summary": "string",
  "evidence": ["string"],
  "why_it_matters": "string",
  "recommended_action": "string",
  "confidence": "low | medium | high"
}
```

**Key files:**

- `apps/api/routes/alert_explanations.py` — route handler (`POST /alerts/{id}/explain`)
- `apps/api/services/rag_explainer.py` — orchestrator: evidence → prompt → LLM → cache
- `apps/api/services/evidence_retrieval.py` — type-specific SQL evidence retrieval
- `apps/api/services/llm_client.py` — GPT-4o wrapper with tenacity retry and `LLMUnavailableError`
- `apps/api/repos/alert_explanations.py` — `get_alert()` and `save_explanation()`
- `apps/api/tests/test_rag_explainer.py` — full test coverage including fallback paths
- `scripts/explain_alert.py` — CLI for local manual testing (`python scripts/explain_alert.py --alert-id <uuid>`)

**DB schema additions** (on the `alerts` table):

- `explanation_text TEXT` — human-readable explanation
- `explanation_json JSONB` — structured LLM output
- `explanation_generated_at TIMESTAMPTZ` — generation timestamp

**Graceful degradation:** If `OPENAI_API_KEY` is unset or the LLM call fails after retries, the service returns a deterministic template-based explanation instead of erroring.

### Code Layout

- `apps/api/routes/` — FastAPI route handlers (thin, delegate to services/repos)
- `apps/api/services/` — business logic (extraction, scoring, alert notifications, SSE, RAG explanations)
- `apps/api/repos/` — all SQL queries (no ORM; raw psycopg3)
- `apps/api/models/` — Pydantic request/response models
- `apps/api/worker/tasks.py` — ARQ job definitions
- `apps/web/app/(app)/` — protected Next.js pages
- `apps/web/app/(auth)/` — magic-link login pages
- `apps/web/lib/apiClient.ts` — client-side typed fetch (uses `packages/client`)
- `apps/web/lib/serverApiClient.ts` — server-side fetch with trusted headers
- `packages/client/` — auto-generated OpenAPI fetch client (TypeScript)
- `packages/types/api.d.ts` — auto-generated TypeScript types from `openapi.json`

## Key Conventions

- **No ORM:** All database access uses raw psycopg3 queries in `repos/`. Use async connections for request handlers, sync connections in the worker.
- **Type safety:** Frontend API calls must use the typed client from `packages/client`. After any backend model change, regenerate with `make openapi && make types`.
- **Idempotent ingestion:** Raw docs are deduplicated by SHA-256 hash — the `(org_id, sha256)` unique constraint prevents re-processing the same file.
- **202 pattern:** Long-running operations (extraction, scoring) always return `202 Accepted` with a `job_id`; the frontend polls `GET /jobs/{job_id}` or listens on the SSE stream.
- **Python dependencies:** Always activate the venv before installing packages (`source venv/bin/activate`). Never install globally.

## Environment

Copy `.env.example` to `.env.local`. Required for full functionality:

- `OPENAI_API_KEY` — GPT-4o extraction
- `DATABASE_URL` — PostgreSQL (set automatically when using `make up`)
- `NEXTAUTH_SECRET` — any random string for local dev
- `SENDGRID_API_KEY` — magic-link emails in production (MailHog handles this locally)

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs on every push:

1. `test-api` — pytest with live Postgres + Redis services
2. `test-web` — Vitest
3. `build-web` — Next.js build

Railway handles deployment automatically via its native GitHub integration — no CI deploy step needed.
