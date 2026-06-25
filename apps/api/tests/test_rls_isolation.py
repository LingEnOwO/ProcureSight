"""
Multi-tenancy / Row-Level Security (RLS) isolation tests.

These lock down the security-critical guarantee that org-scoped tables only
ever expose rows belonging to the org named in the ``app.org_id`` GUC. Any
refactor of how that GUC is set (e.g. the planned org-scoped DB dependency)
must keep every assertion in this file green.

WHY THESE TESTS CONNECT AS ``app_user`` AND NOT ``procure``
-----------------------------------------------------------
RLS on the ProcureSight tables is ENABLED but not FORCED, and the seed user
``procure`` is a *superuser* — superusers bypass RLS entirely. The application
deliberately connects to Postgres as the non-superuser ``app_user`` so policies
are enforced (see ``settings.DATABASE_APP_URL`` and the role setup in
``scripts/seed.py``). Testing isolation therefore *requires* the
non-superuser connection — running these assertions as ``procure`` would
silently pass even if every policy were dropped.

Setup/teardown uses the superuser connection (it can write any org's rows
directly, bypassing RLS); the assertions use the ``app_user`` connection.
Test data is committed so the ``app_user`` connection (a separate session) can
see it, and is removed in teardown via ``DELETE FROM orgs`` (ON DELETE CASCADE
cleans up vendors/invoices/lines/alerts).
"""
import os
import uuid

import psycopg
import pytest
from psycopg.errors import InsufficientPrivilege


# Superuser URL — bypasses RLS; used only for setup/teardown.
SUPERUSER_URL = os.getenv(
    "DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight"
)
# Non-superuser URL — RLS enforced; this is what the assertions run against.
APP_USER_URL = os.getenv(
    "DATABASE_APP_URL", "postgresql://app_user:app_password@localhost:5432/procuresight"
)


# ---------------------------------------------------------------------------
# Precondition guard
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _require_app_user():
    """Skip the module if the non-superuser app_user role is not reachable.

    These tests are only meaningful against a seeded DB that provisions
    ``app_user`` (see scripts/seed.py). In environments that lack it we skip
    rather than emit a confusing connection error.
    """
    try:
        with psycopg.connect(APP_USER_URL):
            pass
    except psycopg.OperationalError as e:
        pytest.skip(
            f"app_user connection unavailable ({e}); RLS tests require the "
            "non-superuser role created by scripts/seed.py"
        )


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def admin_conn():
    """Superuser connection — for committing/removing cross-org fixtures."""
    with psycopg.connect(SUPERUSER_URL) as conn:
        yield conn
        conn.rollback()


@pytest.fixture(scope="module")
def app_conn():
    """Non-superuser connection — RLS is enforced here."""
    with psycopg.connect(APP_USER_URL) as conn:
        yield conn
        conn.rollback()


# ---------------------------------------------------------------------------
# Cross-org fixture data (committed, then torn down)
# ---------------------------------------------------------------------------

def _seed_org(cur, org_id, label):
    """Insert one org + vendor + invoice + line + alert. Returns the ids."""
    vendor_id = str(uuid.uuid4())
    invoice_id = str(uuid.uuid4())
    line_id = str(uuid.uuid4())
    alert_id = str(uuid.uuid4())

    cur.execute("INSERT INTO orgs (id, name) VALUES (%s, %s)", (org_id, label))
    cur.execute(
        "INSERT INTO vendors (id, org_id, name) VALUES (%s, %s, %s)",
        (vendor_id, org_id, f"Vendor {label}"),
    )
    cur.execute(
        """
        INSERT INTO invoices
          (id, org_id, vendor_id, invoice_no, invoice_date, currency, subtotal, tax, total, status)
        VALUES (%s, %s, %s, %s, '2024-01-15', 'USD', 100, 0, 100, 'received')
        """,
        (invoice_id, org_id, vendor_id, f"INV-{label}"),
    )
    cur.execute(
        """
        INSERT INTO invoice_lines (id, invoice_id, sku, "desc", qty, unit_price, line_total)
        VALUES (%s, %s, %s, %s, 1, 100, 100)
        """,
        (line_id, invoice_id, f"SKU-{label}", f"Line {label}"),
    )
    cur.execute(
        """
        INSERT INTO alerts (id, org_id, vendor_id, invoice_id, type, severity, message, meta_json)
        VALUES (%s, %s, %s, %s, 'unit_price_delta', 'high', %s, '{}')
        """,
        (alert_id, org_id, vendor_id, invoice_id, f"Alert {label}"),
    )
    return {
        "org_id": org_id,
        "vendor_id": vendor_id,
        "invoice_id": invoice_id,
        "line_id": line_id,
        "alert_id": alert_id,
    }


@pytest.fixture(scope="module")
def two_orgs(admin_conn):
    """Two fully-populated orgs, committed so the app_user session can see them."""
    org_a = str(uuid.uuid4())
    org_b = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]
    with admin_conn.cursor() as cur:
        a = _seed_org(cur, org_a, f"rls-A-{suffix}")
        b = _seed_org(cur, org_b, f"rls-B-{suffix}")
    admin_conn.commit()

    yield {"a": a, "b": b}

    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM orgs WHERE id = ANY(%s)", ([org_a, org_b],))
    admin_conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scope_to(conn, org_id):
    """Start a clean transaction on ``conn`` scoped to ``org_id`` via the GUC.

    Uses is_local=true so the setting is reset by the next rollback. Pass
    org_id=None to leave the GUC unset (simulating a request that forgot it).
    """
    conn.rollback()  # end any prior tx → clears previously set local GUCs
    if org_id is not None:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))


def _ids(conn, sql, params=None):
    # NB: pass params=None (not ()) so psycopg does not treat the '%' in LIKE
    # patterns as a placeholder.
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return {str(r[0]) for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Precondition: the app connection must be a non-superuser, or these tests
# would pass vacuously (a superuser bypasses RLS).
# ---------------------------------------------------------------------------

def test_app_connection_is_non_superuser(app_conn):
    with app_conn.cursor() as cur:
        cur.execute(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        is_super = cur.fetchone()[0]
    assert is_super is False, (
        "RLS tests must run as a non-superuser (DATABASE_APP_URL must point at "
        "app_user). A superuser bypasses RLS, making these assertions meaningless."
    )


# ---------------------------------------------------------------------------
# SELECT isolation
# ---------------------------------------------------------------------------

def test_org_a_sees_only_its_own_rows(app_conn, two_orgs):
    a, b = two_orgs["a"], two_orgs["b"]
    _scope_to(app_conn, a["org_id"])

    vendors = _ids(app_conn, "SELECT id FROM vendors WHERE name LIKE 'Vendor rls-%'")
    invoices = _ids(app_conn, "SELECT id FROM invoices WHERE invoice_no LIKE 'INV-rls-%'")
    alerts = _ids(app_conn, "SELECT id FROM alerts WHERE message LIKE 'Alert rls-%'")

    assert vendors == {a["vendor_id"]}, "Org A must see exactly its own vendor"
    assert invoices == {a["invoice_id"]}
    assert alerts == {a["alert_id"]}
    # Explicitly assert org B's rows are NOT leaking through.
    assert b["vendor_id"] not in vendors
    assert b["invoice_id"] not in invoices
    assert b["alert_id"] not in alerts


def test_org_b_sees_only_its_own_rows(app_conn, two_orgs):
    a, b = two_orgs["a"], two_orgs["b"]
    _scope_to(app_conn, b["org_id"])

    vendors = _ids(app_conn, "SELECT id FROM vendors WHERE name LIKE 'Vendor rls-%'")
    invoices = _ids(app_conn, "SELECT id FROM invoices WHERE invoice_no LIKE 'INV-rls-%'")

    assert vendors == {b["vendor_id"]}
    assert invoices == {b["invoice_id"]}
    assert a["vendor_id"] not in vendors
    assert a["invoice_id"] not in invoices


def test_invoice_lines_isolation_via_join_policy(app_conn, two_orgs):
    """invoice_lines has no org_id; its policy joins through invoices.

    Verify a line is visible only under its owning org's scope.
    """
    a, b = two_orgs["a"], two_orgs["b"]

    _scope_to(app_conn, a["org_id"])
    lines_a = _ids(app_conn, "SELECT id FROM invoice_lines WHERE sku LIKE 'SKU-rls-%'")
    assert lines_a == {a["line_id"]}
    assert b["line_id"] not in lines_a

    _scope_to(app_conn, b["org_id"])
    lines_b = _ids(app_conn, "SELECT id FROM invoice_lines WHERE sku LIKE 'SKU-rls-%'")
    assert lines_b == {b["line_id"]}


# ---------------------------------------------------------------------------
# Missing GUC must be a safe failure (no rows), never a leak
# ---------------------------------------------------------------------------

def test_missing_guc_returns_no_rows(two_orgs):
    """A request that never sets app.org_id must see zero org-scoped rows.

    current_setting('app.org_id', true) returns NULL on a connection where the
    GUC was never set; `org_id = NULL` is never true, so RLS filters every row.
    This guards against a refactor that accidentally drops the GUC and would
    otherwise expose all tenants.

    Uses its own fresh connection on purpose: once a custom GUC has been touched
    in a session it resets to '' (empty string) rather than NULL, so the truly
    "never set" state — what a freshly-leased pool connection looks like — can
    only be observed on a pristine session.
    """
    with psycopg.connect(APP_USER_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('app.org_id', true)")
            assert cur.fetchone()[0] is None, "GUC must be unset for this test"

        assert _ids(conn, "SELECT id FROM vendors WHERE name LIKE 'Vendor rls-%'") == set()
        assert _ids(conn, "SELECT id FROM invoices WHERE invoice_no LIKE 'INV-rls-%'") == set()
        assert _ids(conn, "SELECT id FROM alerts WHERE message LIKE 'Alert rls-%'") == set()


# ---------------------------------------------------------------------------
# WITH CHECK: cannot write rows into another org
# ---------------------------------------------------------------------------

def test_insert_into_foreign_org_is_rejected(app_conn, two_orgs):
    a, b = two_orgs["a"], two_orgs["b"]
    _scope_to(app_conn, a["org_id"])  # scoped to A...

    with pytest.raises(InsufficientPrivilege) as exc:
        with app_conn.cursor() as cur:
            # ...but trying to insert a row owned by B.
            cur.execute(
                "INSERT INTO vendors (org_id, name) VALUES (%s, %s)",
                (b["org_id"], "smuggled-vendor"),
            )
    assert "row-level security" in str(exc.value).lower()
    app_conn.rollback()  # clear the aborted transaction


# ---------------------------------------------------------------------------
# Documents the security assumption: a superuser bypasses RLS. This is *why*
# the app must connect as app_user; if this ever changes, the comment above
# (and the connection role) needs revisiting.
# ---------------------------------------------------------------------------

def test_superuser_bypasses_rls(admin_conn, two_orgs):
    a, b = two_orgs["a"], two_orgs["b"]
    admin_conn.rollback()
    with admin_conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, true)", (a["org_id"],))
    vendors = _ids(admin_conn, "SELECT id FROM vendors WHERE name LIKE 'Vendor rls-%'")
    admin_conn.rollback()

    # Even though the GUC is scoped to A, the superuser sees BOTH orgs' rows.
    assert {a["vendor_id"], b["vendor_id"]} <= vendors
