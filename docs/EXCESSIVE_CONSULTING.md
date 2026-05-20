# Excessive Consulting — Vector-Search RAG Anomaly

This document describes how to set up, run, and test the `excessive_consulting` anomaly, which is the first vector-search RAG anomaly in ProcureSight.

---

## Overview

The `excessive_consulting` detector flags invoices where consulting or professional-services line items appear to exceed contract or policy rate limits. It uses pgvector to retrieve relevant contract/policy clauses as evidence, then generates a structured explanation using the existing LLM explanation system.

---

## Prerequisites

- Docker running (`make up`)
- Python venv activated (`source venv/bin/activate`)
- `OPENAI_API_KEY` set in `.env.local` for embeddings and LLM explanations (optional — fallback templates work without it)

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | *(empty)* | Required for embedding generation and LLM explanations. If unset, chunks are stored without embeddings and deterministic fallback explanations are used. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model. |
| `EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions (must match the model). |
| `DATABASE_URL` | auto via `make up` | Superuser Postgres URL for migrations and indexing. |

---

## Initial Setup

### 1. Apply the schema

The `doc_chunks` table and pgvector extension are added by `make seed`:

```bash
make up
make seed
```

Verify:

```sql
SELECT table_name FROM information_schema.tables WHERE table_name = 'doc_chunks';
SELECT extname FROM pg_extension WHERE extname = 'vector';
```

### 2. Generate the dataset (if not already done)

```bash
source venv/bin/activate
python dataset/generators/run_all.py
```

### 3. Index contracts and policies

```bash
source venv/bin/activate
python scripts/index_documents.py \
    --contracts-dir dataset/generated/contracts \
    --policies-dir  dataset/generated/policies
```

The script auto-detects the Demo Org. Pass `--org-id <uuid>` to target a different org.

Re-running is safe — it updates existing chunks in place (idempotent via `ON CONFLICT DO UPDATE`).

---

## How Detection Works

1. During `score_invoice_job`, `_score_excessive_consulting_for_invoice()` runs alongside the other four scoring rules.
2. It identifies invoice lines whose `desc` contains consulting keywords: `consulting`, `advisory`, `professional services`, `professional fee`, `services fee`, `hourly`, `strategy`, `management consulting`.
3. For matching lines, it does a vector search on `doc_chunks` using the line descriptions combined with the query `"consulting rate limit professional services cap hourly rate"`.
4. Retrieved chunks are scanned for hourly rate patterns (e.g. `$150.00 per hour`).
5. Alert severity:
   - **`high`** — invoice hourly rate exceeds a contract rate limit found in retrieved chunks.
   - **`medium`** — consulting total > $5,000 and no contract rate limit was found.

The retrieved vector evidence is stored in `alerts.meta_json` under `vector_evidence` so the explanation system can reuse it without a second search.

---

## Trigger the Anomaly Manually

Upload a consulting invoice (JSON example):

```json
{
  "invoice_no": "CONS-TEST-001",
  "vendor": "Acme Consulting LLC",
  "invoice_date": "2026-05-01",
  "due_date": "2026-05-31",
  "currency": "USD",
  "subtotal": 13750.00,
  "tax": 0,
  "total": 13750.00,
  "lines": [
    {
      "sku": "CONS-SVC",
      "desc": "Professional Services Consulting",
      "qty": 50,
      "unit_price": 275.00,
      "line_total": 13750.00
    }
  ]
}
```

Or inject directly into the DB (requires a vendor to already exist):

```sql
-- After seeding and indexing, check for excessive_consulting alerts:
SELECT id, type, severity, message, meta_json->>'consulting_total' AS total
FROM alerts
WHERE type = 'excessive_consulting'
ORDER BY created_at DESC;
```

---

## Generate an Explanation

```bash
python scripts/explain_alert.py --alert-id <uuid>
```

Or via API:

```bash
curl -X POST http://localhost:8000/alerts/<uuid>/explain \
     -H "X-Org-Id: <org-uuid>" \
     -H "X-Business-User-Id: <user-uuid>"
```

---

## Running the Tests

```bash
source venv/bin/activate
pytest apps/api/tests/test_excessive_consulting.py -v
```

The tests require a running Postgres instance (set `DATABASE_URL`). They create isolated fixtures and roll back on teardown.

---

## Key Files

| File | Purpose |
|------|---------|
| `apps/api/services/embeddings.py` | OpenAI embedding generation |
| `apps/api/services/doc_indexer.py` | Document chunking and upsert pipeline |
| `apps/api/services/vector_retrieval.py` | Cosine similarity search over `doc_chunks` |
| `apps/api/services/anomaly_scoring.py` | `_score_excessive_consulting_for_invoice()` |
| `apps/api/services/evidence_retrieval.py` | `retrieve_excessive_consulting()` |
| `apps/api/services/rag_explainer.py` | `_fallback_excessive_consulting()` |
| `scripts/index_documents.py` | CLI to index contracts/policies |
| `scripts/seed.py` | Schema: pgvector extension + `doc_chunks` table |

---

## Extending to New RAG Anomaly Types

To add a new vector-search anomaly (e.g. `unusual_currency`, `vendor_name_variation`):

1. Add a scorer function `_score_<type>_for_invoice()` in `anomaly_scoring.py` and call it from `score_invoice()`.
2. Add `retrieve_<type>()` in `evidence_retrieval.py` and extend the `retrieve_evidence()` dispatcher.
3. Add `_fallback_<type>()` in `rag_explainer.py` and extend `_generate_fallback()`.
4. Add `"<type>"` to `SUPPORTED_TYPES` in `rag_explainer.py`.
5. Reuse `search_chunks()` from `vector_retrieval.py` for retrieval — no new infrastructure needed.
