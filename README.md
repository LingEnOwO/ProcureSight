# ProcureSight

AI-assisted invoice processing and anomaly detection system designed for small-to-medium procurement teams, automating workflows by extracting structured data from invoices, validating business logic, and surfacing high-confidence alerts for price deviations and spend anomalies.

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
- Confidence scoring and validation to flag invoices that need human review
- Idempotent ingestion pipeline with SHA-256 deduplication

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Next.js Web App                         │
│                  (Auth, Uploads UI, Alerts UI)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ Typed API Client (OpenAPI)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI API                             │
│                                                                 │
│  POST /api/ingest        ──────────────────▶  MinIO             │
│  POST /extract/structured                   (S3-compatible)     │
│  POST /extract/unstructured                                     │
│  GET  /invoices                                                 │
│  GET  /alerts                                                   │
│  PATCH /alerts/{id}                                             │
│  GET  /events (SSE)                                             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ psycopg (direct connection)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         PostgreSQL                              │
│                                                                 │
│  Tables: invoices, invoice_lines, alerts, vendors, raw_docs    │
│  Views: vendor_unit_price_stats, vendor_spend_stats            │
│  RLS: org_id scoping enforced per session                      │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             │ Scoring triggers
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Alerts + Notifications                       │
│                                                                 │
│  • Slack Webhook (instant notifications)                       │
│  • SSE Events (real-time UI updates)                           │
└─────────────────────────────────────────────────────────────────┘
```

**Flow in Plain Language:**

A user uploads an invoice (PDF, CSV, or JSON) through the web app. The ingestion API computes a SHA-256 hash for deduplication, stores the raw file in MinIO, and records metadata in Postgres. The extraction pipeline parses the invoice (using pdfplumber for PDFs or direct parsing for structured formats), validates business rules (line math, totals), and persists normalized data. Immediately after persistence, the scoring engine runs rule-based anomaly checks against vendor baselines. Any detected anomalies generate alerts that are written to the database, posted to Slack, and broadcast via SSE to connected web clients. The frontend displays invoices and alerts through a fully typed API client generated from the OpenAPI spec.

---

## What's Implemented (v0)

**Backend (FastAPI + Postgres + MinIO):**

- ✅ **File ingestion** with idempotent uploads via SHA-256 hashing and `(org_id, sha256)` unique constraints
- ✅ **Invoice extraction** from structured inputs (CSV, JSON) and unstructured text-based PDFs using pdfplumber + LLM
- ✅ **Validation + confidence scoring** with Pydantic schemas, business rule checks (line math, totals), and per-field confidence
- ✅ **Rule-based anomaly detection** using vendor unit price baselines, spend spike detection, and duplicate invoice heuristics
- ✅ **Alerts system** with Postgres storage, Slack webhook notifications, and SSE real-time events
- ✅ **Alert APIs** for filtered listing (`GET /alerts`) and status updates (`PATCH /alerts/{id}`)
- ✅ **Row-Level Security (RLS)** enforcement via `app.org_id` session variables for multi-tenant data isolation

**Frontend (Next.js + TypeScript):**

- ✅ **Magic-link authentication** using Auth.js / NextAuth with MailHog for local email delivery
- ✅ **Typed API client** auto-generated from OpenAPI spec for compile-time safety
- ✅ **Uploads UI** for file ingestion with real-time SSE feedback
- ✅ **Read-only Alerts UI** displaying alerts with severity, status, and invoice references
- ✅ **Dashboard, Vendors, and Invoices pages** with real backend data

**Infrastructure:**

- ✅ **Docker Compose** setup for Postgres, MinIO, and MailHog
- ✅ **Makefile** shortcuts for common tasks (`make up`, `make seed`, `make types`)
- ✅ **Database migrations** and seed data for local development

---

## What's Intentionally Not Built Yet

The following items are intentionally out of scope for the current MVP:

- ❌ **No background workers or async job queues** — all processing is synchronous for v0 simplicity
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
# Start infrastructure (Postgres, MinIO, MailHog)
make up

# Create database schema
make seed

# Start FastAPI server
uvicorn apps.api.main:app --reload --port 8000
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
- **Frontend integration** — wired Next.js app to typed API client, implemented magic-link auth, and built read-only UIs for uploads and alerts
- **Local dev infrastructure** — configured Docker Compose for Postgres, MinIO, and MailHog with Makefile automation for common workflows

---

## Tech Stack

**Frontend:** Next.js 14 (App Router), TypeScript, Auth.js, openapi-fetch  
**Backend:** FastAPI, Pydantic, psycopg, pdfplumber  
**Data:** PostgreSQL 15, MinIO (S3-compatible)  
**Dev Tools:** Docker Compose, MailHog, Makefile  
**Integrations:** Slack webhooks, Server-Sent Events (SSE)
