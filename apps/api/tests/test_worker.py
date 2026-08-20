"""
Characterization tests for the ARQ worker jobs (plan item 4.6).

Covers:
  * extract_document — happy path (structured JSON → persisted invoice + scoring
    job enqueued) and the duplicate path (re-submitted invoice → duplicate_invoice
    alert, SSE published, NO scoring job enqueued).
  * score_invoice_job — persists scored alerts, sends a Slack notification, and
    publishes an SSE event per alert.

Strategy
--------
The jobs reach out to S3, ARQ and Redis. We avoid all of that:
  * S3 is bypassed by patching tasks._fetch_s3_bytes to return our bytes.
  * ARQ/Redis are replaced with in-memory fakes that record enqueue/publish calls.
  * The sync DB pool is swapped for a freshly-opened app_user pool (so we don't
    depend on the app lifespan having opened the module-global pool).
  * For score_invoice_job we patch tasks.score_invoice (its rules are already
    covered by test_anomaly_scoring) so the test focuses on persistence +
    notifications, and patch tasks.send_alert_to_slack to avoid the network.

The worker pool connects as app_user, so RLS is in force; setup/teardown use the
superuser connection. The module skips if app_user is unreachable.
"""
import json
import os
import uuid

import psycopg
import pytest
from psycopg_pool import ConnectionPool
from unittest.mock import AsyncMock

from apps.api.worker import tasks
from apps.api.models.alert import AlertCandidate


SUPERUSER_URL = os.getenv(
    "DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight"
)
APP_USER_URL = os.getenv(
    "DATABASE_APP_URL", "postgresql://app_user:app_password@localhost:5432/procuresight"
)


# ---------------------------------------------------------------------------
# In-memory fakes for ARQ / async DB pool
# ---------------------------------------------------------------------------

class FakeArqPool:
    def __init__(self):
        self.enqueued = []
        self.published = []

    async def enqueue_job(self, name, **kwargs):
        self.enqueued.append((name, kwargs))

    async def publish(self, channel, payload):
        self.published.append((channel, payload))


class _FakeAsyncConn:
    async def execute(self, *args, **kwargs):
        return None


class _FakeAsyncCtx:
    async def __aenter__(self):
        return _FakeAsyncConn()

    async def __aexit__(self, *args):
        return False


class FakeAsyncPool:
    """Stands in for ctx['db_pool']; scoring itself is patched out."""
    def connection(self):
        return _FakeAsyncCtx()


# ---------------------------------------------------------------------------
# Guards / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _require_db():
    try:
        with psycopg.connect(SUPERUSER_URL):
            pass
        with psycopg.connect(APP_USER_URL):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"database unavailable ({e}); worker tests need a seeded DB + app_user")


@pytest.fixture
def patched_sync_pool(monkeypatch):
    """Swap tasks.sync_pool for a freshly-opened app_user pool for this test."""
    pool = ConnectionPool(APP_USER_URL, min_size=1, max_size=2, open=True)
    monkeypatch.setattr(tasks, "sync_pool", pool)
    yield pool
    pool.close()


@pytest.fixture(scope="module")
def admin_conn():
    with psycopg.connect(SUPERUSER_URL) as conn:
        yield conn
        conn.rollback()


@pytest.fixture(scope="module")
def wk(admin_conn):
    """An org + a raw_doc (for extract tests) + a vendor & invoice (for the
    score test). Committed; removed on teardown."""
    org = str(uuid.uuid4())
    vendor = str(uuid.uuid4())
    invoice = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]
    with admin_conn.cursor() as cur:
        cur.execute("INSERT INTO orgs (id, name) VALUES (%s, %s)", (org, f"wk-{suffix}"))
        cur.execute(
            """
            INSERT INTO raw_docs (id, org_id, s3_key, filename, mime, bytes, sha256)
            VALUES (DEFAULT, %s, 's3/key', 'f.json', 'application/json', 10, %s)
            RETURNING id
            """,
            (org, "a" * 64),
        )
        raw_doc_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO vendors (id, org_id, name) VALUES (%s, %s, %s)",
            (vendor, org, f"WK Vendor {suffix}"),
        )
        cur.execute(
            """
            INSERT INTO invoices
              (id, org_id, vendor_id, invoice_no, invoice_date, currency, subtotal, tax, total, status)
            VALUES (%s, %s, %s, %s, '2024-01-15', 'USD', 100, 0, 100, 'received')
            """,
            (invoice, org, vendor, f"WK-SCORE-{suffix}"),
        )
    admin_conn.commit()

    yield {"org": org, "raw_doc_id": raw_doc_id, "vendor": vendor, "invoice": invoice}

    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM orgs WHERE id = %s", (org,))
    admin_conn.commit()


def _invoice_json(invoice_no, vendor="Worker Vendor", total=100.0):
    return json.dumps({
        "invoice_no": invoice_no,
        "vendor": vendor,
        "invoice_date": "2024-05-01",
        "due_date": None,
        "currency": "USD",
        "subtotal": total,
        "tax": 0,
        "total": total,
        "lines": [
            {"sku": "S1", "desc": "Item", "qty": 1, "unit_price": total, "line_total": total},
        ],
    }).encode()


def _count(admin_conn, sql, params):
    with admin_conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


# ===========================================================================
# extract_document
# ===========================================================================

@pytest.mark.anyio
async def test_extract_document_happy_path(admin_conn, wk, patched_sync_pool, monkeypatch):
    invoice_no = f"WK-HAPPY-{uuid.uuid4().hex[:6]}"
    monkeypatch.setattr(tasks, "_fetch_s3_bytes", lambda key: _invoice_json(invoice_no))
    arq = FakeArqPool()

    result = await tasks.extract_document(
        {"arq_pool": arq},
        org_id=wk["org"],
        raw_doc_id=wk["raw_doc_id"],
        s3_key="s3/key",
        doc_type="structured_json",
        filename="f.json",
        content_type="application/json",
    )

    assert result["ok"] is True
    assert result["invoice_id"] is not None
    # a scoring job was enqueued for the new invoice
    assert len(arq.enqueued) == 1
    name, kwargs = arq.enqueued[0]
    assert name == "score_invoice_job"
    assert kwargs["invoice_id"] == result["invoice_id"]
    # the invoice and its extraction row were persisted
    assert _count(admin_conn,
                  "SELECT count(*) FROM invoices WHERE org_id=%s AND invoice_no=%s",
                  (wk["org"], invoice_no)) == 1
    assert _count(admin_conn,
                  "SELECT count(*) FROM extractions WHERE raw_doc_id=%s AND invoice_id=%s",
                  (wk["raw_doc_id"], result["invoice_id"])) == 1


@pytest.mark.anyio
async def test_extract_document_duplicate_path(admin_conn, wk, patched_sync_pool, monkeypatch):
    invoice_no = f"WK-DUP-{uuid.uuid4().hex[:6]}"
    monkeypatch.setattr(tasks, "_fetch_s3_bytes", lambda key: _invoice_json(invoice_no))

    # First submission persists the invoice and enqueues scoring.
    arq1 = FakeArqPool()
    first = await tasks.extract_document(
        {"arq_pool": arq1}, org_id=wk["org"], raw_doc_id=wk["raw_doc_id"], s3_key="k",
        doc_type="structured_json", filename="f.json", content_type="application/json",
    )
    assert first["ok"] is True
    assert len(arq1.enqueued) == 1

    # Second submission of the same (vendor, invoice_no) is detected as duplicate:
    # an alert is raised + SSE published, and NO scoring job is enqueued.
    arq2 = FakeArqPool()
    second = await tasks.extract_document(
        {"arq_pool": arq2}, org_id=wk["org"], raw_doc_id=wk["raw_doc_id"], s3_key="k",
        doc_type="structured_json", filename="f.json", content_type="application/json",
    )
    assert second["ok"] is True
    assert second["invoice_ids"] == []
    assert arq2.enqueued == []                 # not re-scored
    assert len(arq2.published) == 1            # SSE duplicate event published
    assert _count(admin_conn,
                  "SELECT count(*) FROM alerts WHERE org_id=%s AND type='duplicate_invoice'",
                  (wk["org"],)) >= 1


# ===========================================================================
# score_invoice_job
# ===========================================================================

@pytest.mark.anyio
async def test_score_invoice_job_persists_and_notifies(admin_conn, wk, patched_sync_pool, monkeypatch):
    candidate = AlertCandidate(
        org_id=wk["org"],
        invoice_id=wk["invoice"],
        vendor_id=wk["vendor"],
        type="unit_price_delta",
        severity="high",
        message="Unit price spike",
        meta={"rule": "unit_price_delta_vs_median", "ratio": 4.0},
    )
    monkeypatch.setattr(tasks, "score_invoice", AsyncMock(return_value=[candidate]))
    slack = AsyncMock()
    monkeypatch.setattr(tasks, "send_alert_to_slack", slack)

    arq = FakeArqPool()
    result = await tasks.score_invoice_job(
        {"db_pool": FakeAsyncPool(), "arq_pool": arq},
        org_id=wk["org"],
        invoice_id=wk["invoice"],
    )

    assert result == {"ok": True, "alert_count": 1}
    assert slack.await_count == 1                      # Slack notified
    assert len(arq.published) == 1                     # SSE published
    assert _count(admin_conn,
                  "SELECT count(*) FROM alerts WHERE org_id=%s AND invoice_id=%s AND type='unit_price_delta'",
                  (wk["org"], wk["invoice"])) == 1
