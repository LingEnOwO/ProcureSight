"""
Tests for the excessive_consulting RAG anomaly feature.

Covers:
  - document indexing (chunking + upsert)
  - vector retrieval (smoke test with mock embeddings)
  - anomaly scorer detection and non-detection
  - explanation generation with fallback (no LLM key)

All DB tests use module-scoped fixtures and roll back on teardown.
"""
import json
import os
import tempfile
import uuid
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import psycopg
import pytest

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight"
)


# ---------------------------------------------------------------------------
# DB Fixtures (shared across tests that need a real DB)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_conn():
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn
        conn.rollback()


@pytest.fixture(scope="module")
def org_id(db_conn):
    oid = str(uuid.uuid4())
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO orgs (id, name) VALUES (%s, %s)",
            (oid, f"test-consulting-org-{oid[:8]}"),
        )
        cur.execute("SELECT set_config('app.org_id', %s, true)", (oid,))
    return oid


@pytest.fixture(scope="module")
def vendor_id(db_conn, org_id):
    vid = str(uuid.uuid4())
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendors (id, org_id, name) VALUES (%s, %s, %s)",
            (vid, org_id, "Acme Consulting LLC"),
        )
    return vid


def _make_invoice(conn, org_id, vendor_id, invoice_no, total, invoice_date="2024-06-01"):
    with conn.cursor() as cur:
        inv_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO invoices
              (id, org_id, vendor_id, invoice_no, invoice_date, currency, subtotal, tax, total, status)
            VALUES (%s, %s, %s, %s, %s, 'USD', %s, 0, %s, 'received')
            """,
            (inv_id, org_id, vendor_id, invoice_no, invoice_date, total, total),
        )
    return inv_id


def _make_line(conn, invoice_id, sku, desc, unit_price, qty=1):
    with conn.cursor() as cur:
        line_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO invoice_lines (id, invoice_id, sku, "desc", qty, unit_price, line_total)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (line_id, invoice_id, sku, desc, qty, unit_price, float(unit_price) * qty),
        )
    return line_id


def _make_alert(conn, org_id, vendor_id, invoice_id, alert_type, severity, message, meta):
    with conn.cursor() as cur:
        aid = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO alerts (id, org_id, vendor_id, invoice_id, type, severity, message, meta_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (aid, org_id, vendor_id, invoice_id, alert_type, severity, message, json.dumps(meta)),
        )
    return aid


# ---------------------------------------------------------------------------
# 1. Document indexing
# ---------------------------------------------------------------------------

def test_index_documents_stores_chunks(db_conn, org_id):
    """index_documents() should write chunks to doc_chunks for each file."""
    from apps.api.services.doc_indexer import index_documents

    sample_text = (
        "ARTICLE 1 — CONSULTING SERVICES\n\n"
        "The maximum hourly rate for consulting services is $150.00 per hour.\n\n"
        "ARTICLE 2 — PAYMENT TERMS\n\n"
        "Invoices must be paid within 30 days of receipt.\n\n"
        "ARTICLE 3 — SCOPE\n\n"
        "All consulting engagements require a signed Statement of Work."
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "sample_contract.txt")
        with open(filepath, "w") as f:
            f.write(sample_text)

        # Patch embed_texts to avoid needing OPENAI_API_KEY
        fake_vector = [0.1] * 1536
        with patch("apps.api.services.doc_indexer.embed_texts", return_value=[fake_vector, fake_vector, fake_vector]):
            result = index_documents(db_conn, org_id, tmpdir, source_type="contract")

    assert result["files"] == 1
    assert result["indexed"] >= 1

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM doc_chunks WHERE org_id = %s AND source_type = 'contract' AND source_name = 'sample_contract.txt'",
            (org_id,),
        )
        count = cur.fetchone()[0]
    assert count >= 1


def test_index_documents_is_idempotent(db_conn, org_id):
    """Re-indexing the same file should not create duplicate rows."""
    from apps.api.services.doc_indexer import index_documents

    sample_text = "CONSULTING RATE\n\nThe approved rate is $120.00 per hour.\n\nSCOPE\n\nServices require SOW."

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "idempotent_contract.txt")
        with open(filepath, "w") as f:
            f.write(sample_text)

        fake_vector = [0.2] * 1536
        with patch("apps.api.services.doc_indexer.embed_texts", return_value=[fake_vector, fake_vector]):
            index_documents(db_conn, org_id, tmpdir, source_type="contract")
            index_documents(db_conn, org_id, tmpdir, source_type="contract")

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM doc_chunks WHERE org_id = %s AND source_name = 'idempotent_contract.txt'",
            (org_id,),
        )
        count_after_two_runs = cur.fetchone()[0]

    with tempfile.TemporaryDirectory() as tmpdir2:
        filepath2 = os.path.join(tmpdir2, "idempotent_contract.txt")
        with open(filepath2, "w") as f:
            f.write(sample_text)
        fake_vector = [0.2] * 1536
        with patch("apps.api.services.doc_indexer.embed_texts", return_value=[fake_vector, fake_vector]):
            result_once = index_documents(db_conn, org_id, tmpdir2, source_type="contract")

    assert count_after_two_runs == result_once["indexed"], (
        "Double-indexing should not create duplicate chunks"
    )


# ---------------------------------------------------------------------------
# 2. Vector retrieval
# ---------------------------------------------------------------------------

def test_search_chunks_returns_results(db_conn, org_id):
    """search_chunks() should return matching chunks when embeddings are present."""
    from apps.api.services.vector_retrieval import search_chunks

    # Insert a test chunk with a known embedding
    test_org = str(uuid.uuid4())
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO orgs (id, name) VALUES (%s, %s)", (test_org, f"search-test-{test_org[:8]}"))
        vector_str = "[" + ",".join(["0.5"] * 1536) + "]"
        cur.execute(
            """
            INSERT INTO doc_chunks (org_id, source_type, source_name, chunk_index, chunk_text, embedding, meta_json)
            VALUES (%s, 'contract', 'search_test.txt', 0, %s, %s::vector, %s)
            """,
            (test_org, "Consulting rate is $150 per hour.", vector_str, json.dumps({})),
        )

    # Mock embed_texts to return the same vector so cosine similarity = 1.0
    with patch("apps.api.services.vector_retrieval.embed_texts", return_value=[[0.5] * 1536]):
        results = search_chunks(db_conn, test_org, "consulting hourly rate", limit=5)

    assert len(results) >= 1
    assert results[0]["source_name"] == "search_test.txt"
    assert "chunk_text" in results[0]


def test_search_chunks_returns_empty_without_api_key(db_conn, org_id):
    """search_chunks() should return [] gracefully when LLM key is absent."""
    from apps.api.services.vector_retrieval import search_chunks
    from apps.api.services.llm_client import LLMUnavailableError

    with patch("apps.api.services.vector_retrieval.embed_texts", side_effect=LLMUnavailableError("no key")):
        results = search_chunks(db_conn, org_id, "consulting rate limit")

    assert results == []


# ---------------------------------------------------------------------------
# 3. Anomaly scorer
#
# The rule holds no connection: it takes a snapshot and a retrieval port. These
# tests build both by hand, so they need neither Postgres nor pgvector nor an
# embedding API key — which matters more for this rule than any other, since
# every labelled anomaly for it is `future_rag` and contributes nothing to
# current-rule recall. Replaying the captured corpus chunks through the same
# port is covered in test_scoring_corpus_tape.py.
# ---------------------------------------------------------------------------

ORG = "11111111-1111-5111-8111-111111111111"
VENDOR = "22222222-2222-5222-8222-222222222222"
INVOICE = "33333333-3333-5333-8333-333333333333"


def _snapshot(*lines: Dict[str, Any], total: Decimal) -> "InvoiceSnapshot":
    from apps.api.models.invoice_snapshot import InvoiceSnapshot

    return InvoiceSnapshot(
        org_id=ORG,
        invoice={
            "id": INVOICE,
            "org_id": ORG,
            "vendor_id": VENDOR,
            "invoice_no": "CONS-0001",
            "invoice_date": None,
            "due_date": None,
            "total": total,
        },
        lines=list(lines),
    )


def _line(sku: str, desc: str, unit_price: Decimal, qty: Decimal) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "invoice_id": INVOICE,
        "sku": sku,
        "desc": desc,
        "qty": qty,
        "unit_price": unit_price,
        "line_total": unit_price * qty,
    }


def _port(chunks, calls=None):
    """A fake ChunkRetriever that replays `chunks`, recording what it was asked."""

    async def retrieve(*, org_id, query, source_types, limit):
        if calls is not None:
            calls.append({
                "org_id": org_id,
                "query": query,
                "source_types": source_types,
                "limit": limit,
            })
        return [dict(c) for c in chunks]

    return retrieve


@pytest.mark.anyio
async def test_scorer_detects_excessive_consulting():
    """Consulting lines totalling > $5k with no retrieved evidence: medium."""
    from apps.api.services.anomaly_scoring import score_excessive_consulting

    snapshot = _snapshot(
        _line("CONS-001", "Professional Services Consulting", Decimal("300"), Decimal("40")),
        total=Decimal("12000"),
    )

    candidates = await score_excessive_consulting(snapshot, retrieve=_port([]))

    assert len(candidates) == 1
    c = candidates[0]
    assert c.type == "excessive_consulting"
    assert c.severity == "medium"
    assert c.meta["consulting_total"] == pytest.approx(12000.0, abs=1)


@pytest.mark.anyio
async def test_scorer_high_severity_when_rate_exceeded():
    """When contract rate is found and exceeded, severity should be high."""
    from apps.api.services.anomaly_scoring import score_excessive_consulting

    snapshot = _snapshot(
        _line("CONS-002", "Management Consulting Advisory", Decimal("275"), Decimal("30")),
        total=Decimal("8250"),
    )
    fake_chunk = {
        "source_type": "contract",
        "source_name": "test_contract.txt",
        "chunk_text": "The maximum consulting rate is $150.00 per hour for all engagements.",
        "similarity": 0.9,
    }

    candidates = await score_excessive_consulting(snapshot, retrieve=_port([fake_chunk]))

    assert len(candidates) == 1
    c = candidates[0]
    assert c.type == "excessive_consulting"
    assert c.severity == "high"
    assert c.meta["contract_rate_found"] == pytest.approx(150.0, abs=0.1)
    assert c.meta["invoice_rate"] == pytest.approx(275.0, abs=0.1)
    assert c.meta["vector_evidence"][0]["source_name"] == "test_contract.txt"


@pytest.mark.anyio
async def test_scorer_no_alert_without_consulting_lines():
    """Non-consulting invoice should produce no excessive_consulting alert."""
    from apps.api.services.anomaly_scoring import score_excessive_consulting

    snapshot = _snapshot(
        _line("PAPER-A4", "Copy Paper Case", Decimal("45"), Decimal("100")),
        _line("PEN-BLK", "Ballpoint Pens Box", Decimal("8.75"), Decimal("50")),
        total=Decimal("8000"),
    )
    calls: list = []

    assert await score_excessive_consulting(snapshot, retrieve=_port([], calls)) == []
    assert calls == [], "no consulting lines means no question to ask"


@pytest.mark.anyio
async def test_scorer_no_alert_below_threshold():
    """Consulting invoice below threshold with no contract rate should not alert."""
    from apps.api.services.anomaly_scoring import score_excessive_consulting

    snapshot = _snapshot(
        _line("CONS-003", "Advisory Services", Decimal("150"), Decimal("10")),
        total=Decimal("1500"),
    )

    assert await score_excessive_consulting(snapshot, retrieve=_port([])) == []


@pytest.mark.anyio
async def test_the_rule_owns_the_question_it_asks_the_port():
    """The query text is built from the consulting lines, which only the rule can
    classify — the reason this retrieval is injected rather than prefetched."""
    from apps.api.services.anomaly_scoring import score_excessive_consulting

    snapshot = _snapshot(
        _line("CONS-004", "Management Consulting Services", Decimal("400"), Decimal("40")),
        _line("PAPER-A4", "Copy Paper Case", Decimal("45"), Decimal("10")),
        total=Decimal("16450"),
    )
    calls: list = []

    await score_excessive_consulting(snapshot, retrieve=_port([], calls))

    assert calls == [
        {
            "org_id": ORG,
            "query": (
                "Management Consulting Services consulting rate limit "
                "professional services cap hourly rate"
            ),
            "source_types": ["contract", "policy"],
            "limit": 5,
        }
    ]


@pytest.mark.anyio
async def test_scorer_ignores_an_invoice_with_no_lines():
    from apps.api.services.anomaly_scoring import score_excessive_consulting

    assert await score_excessive_consulting(_snapshot(total=Decimal("0")), retrieve=_port([])) == []


# ---------------------------------------------------------------------------
# 4. Explanation fallback (no LLM)
# ---------------------------------------------------------------------------

def test_fallback_explanation_no_llm_key(db_conn, org_id, vendor_id):
    """explain_alert() should return a deterministic fallback when LLM key is absent."""
    from apps.api.services.rag_explainer import explain_alert

    inv_id = _make_invoice(db_conn, org_id, vendor_id, f"CONS-EXP-{uuid.uuid4().hex[:6]}", Decimal("15000"))
    _make_line(db_conn, inv_id, "CONS-EXP", "Consulting Services", Decimal("300"), qty=50)
    db_conn.commit()

    meta = {
        "rule": "excessive_consulting",
        "consulting_total": 15000.0,
        "consulting_lines": [{"desc": "Consulting Services", "qty": 50, "unit_price": 300, "line_total": 15000}],
        "vector_evidence": [
            {
                "source_type": "contract",
                "source_name": "test_contract.txt",
                "snippet": "Maximum consulting rate is $150.00 per hour.",
                "similarity": 0.92,
            }
        ],
        "contract_rate_found": 150.0,
        "invoice_rate": 300.0,
        "invoice_no": "CONS-EXP",
        "invoice_id": inv_id,
        "vendor_id": vendor_id,
    }
    alert_id = _make_alert(
        db_conn, org_id, vendor_id, inv_id,
        "excessive_consulting", "high",
        "Consulting invoice exceeds contract rate limit.",
        meta,
    )
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))

    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        result = explain_alert(db_conn, org_id, alert_id, force=True)

    assert result["alert_type"] == "excessive_consulting"
    assert result["source"] == "template"
    assert result["explanation"]
    llm = result["llm_output"]
    assert llm["confidence"] in {"low", "medium", "high"}
    assert any("150" in e for e in llm["evidence"])
