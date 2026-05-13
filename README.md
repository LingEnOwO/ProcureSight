# ProcureSight

AI-assisted invoice processing, anomaly detection, and alert explanation system designed for small-to-medium procurement teams, automating workflows by extracting structured data from invoices, validating business logic, surfacing high-confidence alerts for price deviations and spend anomalies, and generating LLM-backed explanations grounded in historical invoice evidence.

---

## Problem → Solution

**The Pain Point:**

- Manual invoice review is time-consuming and error-prone
- Price deviations and duplicate invoices often go unnoticed until audit time
- Unstructured PDFs require manual data entry into procurement systems
- No real-time visibility into vendor spend anomalies

**How ProcureSight Addresses It:**

- Automated extraction from structured (CSV/JSON) and unstructured (text-based PDF) invoices
- Rule-based anomaly detection using vendor baselines and historical spend patterns
- Real-time alerts via Slack and SSE for immediate action
- LLM-generated explanations for each alert, grounded in retrieved invoice evidence (RAG)
- Confidence scoring and validation to flag invoices that need human review
- Idempotent ingestion pipeline with SHA-256 deduplication

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Next.js Web App                         │
│         (Auth gateway, Uploads UI, Alerts UI, Dashboard)        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ Gateway (session → trusted headers)
                             │ Server components use serverFetch directly
                             │ Client components use /api/backend/* proxy
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI API                             │
│                                                                 │
│  POST /ingest            ──────────────────▶  MinIO             │
│  POST /extract/structured    (202 + job_id)  (S3-compatible)    │
│  POST /extract/unstructured                                     │
│  GET  /jobs/{job_id}                                            │
│  GET  /invoices                                                 │
│  GET  /alerts                                                   │
│  PATCH /alerts/{id}                                             │
│  POST /alerts/{id}/explain  ◀──── RAG explanation system        │
│  GET  /events (SSE)      ◀──────────────────  Redis pub/sub     │
└────────────────────────────┬────────────────────────────────────┘
                             │ enqueue_job
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Redis + ARQ Worker                         │
│                                                                 │
│  extract_document   — S3 fetch → LLM/parse → validate →        │
│                       persist invoice → enqueue scoring         │
│  score_invoice_job  — anomaly rules → insert alerts →          │
│                       Slack webhook → Redis pub/sub SSE         │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ psycopg3 connection pools (sync + async)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         PostgreSQL                              │
│                                                                 │
│  Tables: invoices, invoice_lines, alerts, vendors, raw_docs     │
│  Views: vendor_unit_price_stats, vendor_spend_stats             │
│  Schemas: public (business data), nextauth (auth tables)        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ Scoring results
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Alerts + Notifications                       │
│                                                                 │
│  • Slack Webhook (instant notifications)                        │
│  • SSE Events via Redis pub/sub (real-time UI updates)          │
└─────────────────────────────────────────────────────────────────┘
```

**Flow in Plain Language:**

A user uploads an invoice (PDF, CSV, or JSON) through the web app. The ingestion API computes a SHA-256 hash for deduplication, stores the raw file in MinIO, and records metadata in Postgres. The extraction endpoint enqueues an ARQ background job and returns a `job_id` immediately (HTTP 202). The ARQ worker fetches the file from S3, parses it (pdfplumber for PDFs or direct parsing for structured formats), validates business rules (line math, totals), and persists normalized invoice data. It then enqueues a second scoring job. The scoring worker runs rule-based anomaly checks against vendor baselines, writes any detected anomalies to the database, posts to Slack, and publishes SSE events via Redis pub/sub to connected web clients. The frontend polls `GET /jobs/{job_id}` for completion and displays invoices and alerts through a fully typed API client generated from the OpenAPI spec. On demand, `POST /alerts/{id}/explain` runs the RAG explanation system: it retrieves type-specific SQL evidence (price history, volume history, or duplicate match fields), builds a prompt, calls GPT-4o for a structured explanation, and caches the result on the alert row for future requests.

---

## What's Implemented (v0)

**Backend (FastAPI + Postgres + MinIO):**

- ✅ **File ingestion** with idempotent uploads via SHA-256 hashing and `(org_id, sha256)` unique constraints
- ✅ **Invoice extraction** from structured inputs (CSV, JSON) and unstructured text-based PDFs using pdfplumber + LLM
- ✅ **Validation + confidence scoring** with Pydantic schemas, business rule checks (line math, totals), and per-field confidence
- ✅ **Rule-based anomaly detection** using vendor unit price baselines, spend spike detection, and duplicate invoice heuristics
- ✅ **Alerts system** with Postgres storage, Slack webhook notifications, and SSE real-time events
- ✅ **Alert APIs** for filtered listing (`GET /alerts`) and status updates (`PATCH /alerts/{id}`)
- ✅ **RAG explanation system** — `POST /alerts/{id}/explain` retrieves structured SQL evidence per alert type, builds a GPT-4o prompt, and returns a cached explanation with `summary`, `evidence`, `why_it_matters`, `recommended_action`, and `confidence`. Falls back to deterministic templates if the LLM is unavailable. Supports `unit_price_delta`, `vendor_volume_spike`, and `duplicate_invoice` alert types
- ✅ **Multi-tenant data isolation** via `org_id` scoping on all queries, enforced through trusted headers from the Next.js gateway. Postgres RLS is enabled and enforced across all routes (sync and async scoring pipeline) via a non-superuser `app_user` role with `app.org_id` GUC-based tenant isolation

**Frontend (Next.js + TypeScript):**

- ✅ **Magic-link authentication** using Auth.js / NextAuth with MailHog for local email delivery
- ✅ **Typed API client** auto-generated from OpenAPI spec for compile-time safety
- ✅ **Uploads UI** for file ingestion with real-time SSE feedback
- ✅ **Read-only Alerts UI** displaying alerts with severity, status, and invoice references
- ✅ **Dashboard, Vendors, and Invoices pages** with real backend data

**Infrastructure:**

- ✅ **Async job queue** with ARQ + Redis — extraction and scoring run in a separate worker process; HTTP endpoints return `{job_id}` immediately (HTTP 202)
- ✅ **Redis pub/sub SSE** — real-time alert events delivered via Redis fan-out, enabling multi-process/pod SSE delivery
- ✅ **Docker Compose** setup for Postgres, MinIO, Redis, and MailHog with automated MinIO bucket creation
- ✅ **Makefile** shortcuts for common tasks (`make up`, `make seed`, `make worker`, `make types`)
- ✅ **Database migrations** and seed data for local development

---

## What's Intentionally Not Built Yet

The following items are intentionally out of scope for the current MVP:

- ❌ **No OCR or image-based PDF support** — only text-based PDFs are extracted
- ❌ **No cloud deployment or IaC** — local Docker-first workflow for development
- ❌ **No alert actions UI** — alerts can be viewed but not acknowledged/dismissed from the frontend yet
- ❌ **No advanced ML models** — baseline rule-based scoring only (Isolation Forest planned for v1)
- ❌ **No production email provider** — MailHog only for local magic-link auth
- ❌ **No multi-tenant user management UI** — org scoping enforced backend-only via RLS

This scoped approach keeps the project focused on **core system design, data flow, and correctness** for an MVP implementation.

---

## How to Run Locally

**Prerequisites:**

- Node.js 20+ and pnpm
- Python 3.11+
- Docker Desktop with Docker Compose v2

**Backend:**

```bash
# Start infrastructure (Postgres, MinIO, Redis, MailHog)
make up

# Create database schema and seed data
make seed

# Start FastAPI server
uvicorn apps.api.main:app --reload --port 8000

# Start ARQ background worker (separate terminal)
make worker
```

**Frontend:**

```bash
# Install dependencies
pnpm install

# Start Next.js dev server
pnpm --filter web dev
```

**Access Points:**

- Web App: http://localhost:3000
- API Docs: http://localhost:8000/docs
- MinIO Console: http://localhost:9001 (minioadmin / minioadmin)
- MailHog UI: http://localhost:8025

**Magic-Link Auth:**

Sign in with any email address. Check MailHog (http://localhost:8025) for the magic link.

---

## What I Owned

- **System architecture design** — defined the end-to-end flow from ingestion through extraction, validation, scoring, and alerting with clear separation of concerns
- **Backend API design** — built RESTful FastAPI endpoints with OpenAPI spec generation, typed request/response models, and SSE for real-time updates
- **Data modeling** — designed Postgres schema with proper normalization, indexes, and Row-Level Security policies for multi-tenant isolation
- **Ingestion pipeline** — implemented idempotent file uploads with SHA-256 deduplication, MinIO storage, and metadata persistence
- **Extraction pipeline** — built unified validation logic for structured (CSV/JSON) and unstructured (PDF) inputs with confidence scoring and business rule checks
- **Anomaly detection logic** — created rule-based scoring engine using vendor baselines (unit price stats, spend patterns) and duplicate detection heuristics
- **RAG explanation system** — designed the evidence retrieval and prompt construction pipeline; built the GPT-4o LLM client with structured JSON output, tenacity retry logic, and graceful fallback to deterministic templates; wired caching into the alerts table
- **Frontend integration** — implemented Next.js gateway pattern (session validation → trusted headers to FastAPI), magic-link auth, and read-only UIs for uploads, alerts, invoices, vendors, and dashboard
- **Local dev infrastructure** — configured Docker Compose for Postgres, MinIO, and MailHog with Makefile automation for common workflows

---

## Tech Stack

**Frontend:** Next.js 16 (App Router), TypeScript, Auth.js, openapi-fetch
**Backend:** FastAPI, Pydantic, psycopg, pdfplumber, ARQ
**Data:** PostgreSQL 15, MinIO (S3-compatible), Redis 7
**Dev Tools:** Docker Compose, MailHog, Makefile
**Integrations:** Slack webhooks, Server-Sent Events (SSE via Redis pub/sub), OpenAI GPT-4o (extraction + RAG explanations)
