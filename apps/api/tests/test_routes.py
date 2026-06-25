"""
HTTP-level integration tests for the FastAPI routes.

These exercise the real app through Starlette's TestClient (so the lifespan
opens the real psycopg pools, ARQ pool and Redis client) and lock down:

  * the trusted-header auth contract (missing headers → 401) — this is the
    contract the planned gateway-auth consolidation (plan item 2.2) must keep,
  * org scoping at the HTTP boundary (one org never sees another's rows),
  * invoices read/update, alerts list/filter/status, jobs polling, and
    ingest SHA-256 de-duplication.

The app's DB pool connects as the non-superuser ``app_user`` (settings.DATABASE_APP_URL),
so RLS is enforced end-to-end here. Test data is seeded/committed with the
superuser connection and removed in teardown (DELETE FROM orgs ... CASCADE).

The module skips itself if the seeded DB / app_user role / Redis are not
available (same rationale as test_rls_isolation.py).
"""
import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.storage import s3_ok


SUPERUSER_URL = os.getenv(
    "DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight"
)
APP_USER_URL = os.getenv(
    "DATABASE_APP_URL", "postgresql://app_user:app_password@localhost:5432/procuresight"
)


# ---------------------------------------------------------------------------
# Infra guards / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _require_db():
    try:
        with psycopg.connect(SUPERUSER_URL):
            pass
        with psycopg.connect(APP_USER_URL):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(f"database unavailable ({e}); route tests need a seeded DB + app_user")


@pytest.fixture(scope="module")
def client():
    """Real app with lifespan (pools/ARQ/Redis). Skips if startup fails."""
    try:
        with TestClient(app) as c:
            yield c
    except Exception as e:  # e.g. Redis/ARQ not reachable
        pytest.skip(f"app startup failed ({e}); route tests need Redis + DB")


@pytest.fixture(scope="module")
def admin_conn():
    with psycopg.connect(SUPERUSER_URL) as conn:
        yield conn
        conn.rollback()


@pytest.fixture(scope="module")
def seeded(admin_conn):
    """Two orgs; org A populated with a user, vendor, invoice (+line), and two
    alerts (one high, one low). Committed; removed on teardown."""
    org_a = str(uuid.uuid4())
    org_b = str(uuid.uuid4())
    user_a = str(uuid.uuid4())
    vendor_a = str(uuid.uuid4())
    invoice_a = str(uuid.uuid4())
    alert_high = str(uuid.uuid4())
    alert_low = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]

    with admin_conn.cursor() as cur:
        cur.execute("INSERT INTO orgs (id, name) VALUES (%s, %s)", (org_a, f"rt-A-{suffix}"))
        cur.execute("INSERT INTO orgs (id, name) VALUES (%s, %s)", (org_b, f"rt-B-{suffix}"))
        cur.execute(
            "INSERT INTO users (id, org_id, email, role) VALUES (%s, %s, %s, 'admin')",
            (user_a, org_a, f"rt-{suffix}@demo.local"),
        )
        cur.execute(
            "INSERT INTO vendors (id, org_id, name) VALUES (%s, %s, %s)",
            (vendor_a, org_a, f"RT Vendor {suffix}"),
        )
        cur.execute(
            """
            INSERT INTO invoices
              (id, org_id, vendor_id, invoice_no, invoice_date, currency, subtotal, tax, total, status)
            VALUES (%s, %s, %s, %s, '2024-01-15', 'USD', 100, 0, 100, 'received')
            """,
            (invoice_a, org_a, vendor_a, f"RT-INV-{suffix}"),
        )
        cur.execute(
            """
            INSERT INTO invoice_lines (id, invoice_id, sku, "desc", qty, unit_price, line_total)
            VALUES (%s, %s, 'SKU1', 'Widget', 1, 100, 100)
            """,
            (str(uuid.uuid4()), invoice_a),
        )
        for aid, sev in ((alert_high, "high"), (alert_low, "low")):
            cur.execute(
                """
                INSERT INTO alerts (id, org_id, vendor_id, invoice_id, type, severity, message, meta_json)
                VALUES (%s, %s, %s, %s, 'unit_price_delta', %s, 'msg', '{}')
                """,
                (aid, org_a, vendor_a, invoice_a, sev),
            )
    admin_conn.commit()

    data = {
        "org_a": org_a, "org_b": org_b, "user_a": user_a, "vendor_a": vendor_a,
        "invoice_a": invoice_a, "invoice_no": f"RT-INV-{suffix}",
        "alert_high": alert_high, "alert_low": alert_low,
    }
    yield data

    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM orgs WHERE id = ANY(%s)", ([org_a, org_b],))
    admin_conn.commit()


def _headers(org_id, user_id="00000000-0000-0000-0000-000000000000", role="admin"):
    return {"x-org-id": org_id, "x-business-user-id": user_id, "x-user-role": role}


# ===========================================================================
# Auth contract (the part plan item 2.2 must preserve)
# ===========================================================================

def test_no_headers_is_401(client):
    assert client.get("/invoices").status_code == 401


def test_missing_org_header_is_401(client):
    r = client.get("/invoices", headers={"x-business-user-id": "u"})
    assert r.status_code == 401


def test_missing_business_user_header_is_401(client):
    r = client.get("/invoices", headers={"x-org-id": str(uuid.uuid4())})
    assert r.status_code == 401


def test_valid_headers_ok(client, seeded):
    assert client.get("/invoices", headers=_headers(seeded["org_a"])).status_code == 200


# ===========================================================================
# Invoices
# ===========================================================================

def test_list_invoices_scoped_to_org(client, seeded):
    no = seeded["invoice_no"]
    r_a = client.get("/invoices", headers=_headers(seeded["org_a"]))
    r_b = client.get("/invoices", headers=_headers(seeded["org_b"]))
    assert r_a.status_code == 200 and r_b.status_code == 200
    assert no in r_a.text          # org A sees its invoice
    assert no not in r_b.text      # org B does not


def test_get_invoice_by_id(client, seeded):
    r = client.get(f"/invoices/{seeded['invoice_a']}", headers=_headers(seeded["org_a"]))
    assert r.status_code == 200
    assert seeded["invoice_no"] in r.text


def test_get_invoice_unknown_id_404(client, seeded):
    r = client.get(f"/invoices/{uuid.uuid4()}", headers=_headers(seeded["org_a"]))
    assert r.status_code == 404


def test_get_invoice_cross_org_is_404(client, seeded):
    """Org B requesting org A's invoice id is hidden by RLS → 404, not 200."""
    r = client.get(f"/invoices/{seeded['invoice_a']}", headers=_headers(seeded["org_b"]))
    assert r.status_code == 404


def test_patch_invoice_updates_field(client, seeded):
    r = client.patch(
        f"/invoices/{seeded['invoice_a']}",
        json={"currency": "EUR"},
        headers=_headers(seeded["org_a"]),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # confirm the change persisted
    g = client.get(f"/invoices/{seeded['invoice_a']}", headers=_headers(seeded["org_a"]))
    assert "EUR" in g.text


def test_create_invoice_persists(client, seeded):
    """POST /invoices writes vendor + invoice + lines (persist_invoice path)."""
    body = {
        "vendor": "Created Vendor",
        "invoice_no": "RT-CREATE-1",
        "invoice_date": "2024-07-01",
        "currency": "USD",
        "subtotal": 50,
        "tax": 0,
        "total": 50,
        "lines": [{"sku": "S", "desc": "Item", "qty": 1, "unit_price": 50, "line_total": 50}],
    }
    r = client.post("/invoices", json=body, headers=_headers(seeded["org_a"]))
    assert r.status_code == 200, r.text
    listing = client.get("/invoices", headers=_headers(seeded["org_a"]))
    assert "RT-CREATE-1" in listing.text


# ===========================================================================
# Alerts
# ===========================================================================

def test_list_alerts_returns_org_alerts(client, seeded):
    r = client.get("/alerts/", headers=_headers(seeded["org_a"]))
    assert r.status_code == 200
    body = r.text
    assert seeded["alert_high"] in body
    assert seeded["alert_low"] in body


def test_list_alerts_filter_by_severity(client, seeded):
    r = client.get("/alerts/?severity=high", headers=_headers(seeded["org_a"]))
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(i["severity"] == "high" for i in items)
    ids = {i["id"] for i in items}
    assert seeded["alert_high"] in ids
    assert seeded["alert_low"] not in ids


def test_patch_alert_acknowledge(client, seeded):
    r = client.patch(
        f"/alerts/{seeded['alert_low']}",
        json={"status": "acknowledged"},
        headers=_headers(seeded["org_a"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] is True
    assert body["status"] == "resolved"
    assert body["acknowledged_at"] is not None


def test_patch_alert_unknown_404(client, seeded):
    r = client.patch(
        f"/alerts/{uuid.uuid4()}",
        json={"status": "acknowledged"},
        headers=_headers(seeded["org_a"]),
    )
    assert r.status_code == 404


def test_patch_alert_cross_org_404(client, seeded):
    """Org B cannot acknowledge org A's alert (RLS update matches no row)."""
    r = client.patch(
        f"/alerts/{seeded['alert_high']}",
        json={"status": "acknowledged"},
        headers=_headers(seeded["org_b"]),
    )
    assert r.status_code == 404


# ===========================================================================
# Jobs
# ===========================================================================

def test_job_status_unknown_is_404(client, seeded):
    r = client.get(f"/jobs/{uuid.uuid4().hex}", headers=_headers(seeded["org_a"]))
    assert r.status_code == 404


# ===========================================================================
# Health
# ===========================================================================

def test_health_reports_db_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db"] is True


# ===========================================================================
# Ingest de-duplication (needs MinIO/S3)
# ===========================================================================

def test_ingest_then_duplicate(client, seeded):
    if not s3_ok():
        pytest.skip("S3/MinIO not available")

    content = b"invoice_no,total\nRT-CSV-1,100\n"
    h = _headers(seeded["org_a"], user_id=seeded["user_a"])

    r1 = client.post("/ingest", files={"file": ("dedup.csv", content, "text/csv")}, headers=h)
    assert r1.status_code == 200, r1.text
    first = r1.json()
    assert first["duplicate"] is False
    raw_doc_id = first["raw_doc_id"]

    # Same bytes again → recognized as duplicate, same raw_doc_id, no new row.
    r2 = client.post("/ingest", files={"file": ("dedup.csv", content, "text/csv")}, headers=h)
    assert r2.status_code == 200, r2.text
    second = r2.json()
    assert second["duplicate"] is True
    assert second["raw_doc_id"] == raw_doc_id
