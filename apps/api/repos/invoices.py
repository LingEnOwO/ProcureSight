from typing import Optional, List, Dict, Any
from psycopg import Connection
from psycopg.rows import dict_row
from decimal import Decimal

# Ensures that a vendor record exists for a given organization and returns its ID.
# Avoids duplicate vendor creation by using ON CONFLICT to upsert.
def ensure_vendor(conn: Connection, org_id: str, name: str) -> str:
    params = {"org_id": org_id, "name": name}
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO vendors (id, org_id, name, created_at)
            VALUES (gen_random_uuid(), %(org_id)s, %(name)s, now())
            ON CONFLICT (org_id, name) DO NOTHING
            RETURNING id;
        """, params)
        row = cur.fetchone()
        if row:
            return row[0]
        # Vendor already existed — fetch its id via SELECT
        cur.execute(
            "SELECT id FROM vendors WHERE org_id = %(org_id)s AND name = %(name)s",
            params,
        )
        existing = cur.fetchone()
        if existing is None:
            raise RuntimeError(
                f"ensure_vendor: vendor not found after upsert (org_id={org_id!r}, name={name!r})"
            )
        return existing[0]

def find_invoice_by_key(
    conn: Connection, org_id: str, vendor_id: str, invoice_no: str
) -> Optional[Dict[str, Any]]:
    """Return {id, raw_doc_id, total, invoice_date} for an existing invoice, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, raw_doc_id, total, invoice_date FROM invoices "
            "WHERE org_id = %s AND vendor_id = %s AND invoice_no = %s",
            (org_id, vendor_id, invoice_no),
        )
        return cur.fetchone()


def insert_invoice(
    conn: Connection, org_id: str, vendor_id: str, payload: dict, raw_doc_id: Optional[int]
) -> str:
    """Pure INSERT — caller must have confirmed no existing row via find_invoice_by_key."""
    sql = """
    INSERT INTO invoices
      (id, org_id, vendor_id, invoice_no, invoice_date, due_date,
       currency, subtotal, tax, total, status, raw_doc_id, created_at)
    VALUES
      (gen_random_uuid(), %(org_id)s, %(vendor_id)s, %(invoice_no)s, %(invoice_date)s, %(due_date)s,
       %(currency)s, %(subtotal)s, %(tax)s, %(total)s, 'received', %(raw_doc_id)s, now())
    RETURNING id;
    """
    with conn.cursor() as cur:
        cur.execute(sql, {
            "org_id": org_id,
            "vendor_id": vendor_id,
            "invoice_no": payload["invoice_no"],
            "invoice_date": payload["invoice_date"],
            "due_date": payload.get("due_date"),
            "currency": payload["currency"],
            "subtotal": Decimal(payload["subtotal"]),
            "tax": Decimal(payload["tax"]),
            "total": Decimal(payload["total"]),
            "raw_doc_id": raw_doc_id,
        })
        return cur.fetchone()[0]


# Inserts or updates an invoice (upsert) for a given vendor/org based on invoice_no.
# Prevents duplicates and ensures invoice data stays consistent when reprocessed.
def upsert_invoice(conn: Connection, org_id: str, vendor_id: str, payload: dict, raw_doc_id: Optional[int]) -> str:
    sql = """
    INSERT INTO invoices
      (id, org_id, vendor_id, invoice_no, invoice_date, due_date,
       currency, subtotal, tax, total, status, raw_doc_id, created_at)
    VALUES
      (gen_random_uuid(), %(org_id)s, %(vendor_id)s, %(invoice_no)s, %(invoice_date)s, %(due_date)s,
       %(currency)s, %(subtotal)s, %(tax)s, %(total)s, 'received', %(raw_doc_id)s, now())
    ON CONFLICT (org_id, vendor_id, invoice_no)
    DO UPDATE SET
      invoice_date = EXCLUDED.invoice_date,
      due_date     = EXCLUDED.due_date,
      currency     = EXCLUDED.currency,
      subtotal     = EXCLUDED.subtotal,
      tax          = EXCLUDED.tax,
      total        = EXCLUDED.total,
      raw_doc_id   = COALESCE(EXCLUDED.raw_doc_id, invoices.raw_doc_id)
    RETURNING id;
    """
    with conn.cursor() as cur:
        cur.execute(sql, {
          "org_id": org_id, 
          "vendor_id": vendor_id,
          "invoice_no": payload["invoice_no"],
          "invoice_date": payload["invoice_date"],
          "due_date": payload.get("due_date"),
          "currency": payload["currency"],
          "subtotal": Decimal(payload["subtotal"]),
          "tax": Decimal(payload["tax"]),
          "total": Decimal(payload["total"]),
          "raw_doc_id": raw_doc_id
        })
        return cur.fetchone()[0]

# Replaces all line items associated with a specific invoice.
# Ensures invoice_lines table reflects the most recent extraction results.
def replace_lines(conn: Connection, invoice_id: str, lines: list[dict]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM invoice_lines WHERE invoice_id = %(id)s", {"id": invoice_id})
        cur.executemany("""
            INSERT INTO invoice_lines
              (id, invoice_id, sku, "desc", qty, unit_price, line_total)
            VALUES
              (gen_random_uuid(), %(invoice_id)s, %(sku)s, %(desc)s, %(qty)s, %(unit_price)s, %(line_total)s)
        """, [{"invoice_id": invoice_id, **ln} for ln in lines])


# Lists invoices for the current org context with pagination.
# LIMIT = page size; OFFSET = start index
def list_invoices(conn: Connection, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, vendor_id, invoice_no, invoice_date, due_date, currency, subtotal, tax, total, status
            FROM invoices
            ORDER BY invoice_date DESC, created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return cur.fetchall()


# Fetches a single invoice and its line items. Returns None if not found.
def get_invoice_with_lines(conn: Connection, invoice_id: str) -> Optional[Dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, vendor_id, invoice_no, invoice_date, due_date, currency, subtotal, tax, total, status
            FROM invoices WHERE id = %s
            """,
            (invoice_id,),
        )
        inv = cur.fetchone()
        if not inv:
            return None

        cur.execute(
            """
            SELECT id, sku, "desc", qty, unit_price, line_total
            FROM invoice_lines WHERE invoice_id = %s ORDER BY id
            """,
            (invoice_id,),
        )
        inv["lines"] = cur.fetchall()
        return inv


# Partially updates invoice scalar fields. `fields` is a dict of column -> value.
# Returns True if a row was updated, False if no such invoice exists.
def update_invoice_fields(conn: Connection, invoice_id: str, fields: Dict[str, Any]) -> bool:
    if not fields:
        return True  # nothing to do; treat as success
    allowed = {"vendor_id", "invoice_no", "invoice_date", "due_date", "currency", "subtotal", "tax", "total", "status"}
    assignments = []
    values = []
    for k, v in fields.items():
        if k in allowed:
            assignments.append(f"{k} = %s")
            values.append(v)
    if not assignments:
        return True
    sql_stmt = f"UPDATE invoices SET {', '.join(assignments)} WHERE id = %s"
    with conn.cursor() as cur:
        cur.execute(sql_stmt, (*values, invoice_id))
        return cur.rowcount > 0

# ---------------------------------------------------------------------------
# The columns scoring reads
#
# Named once, here, because three places select them: the two snapshot reads
# below, the joined read the not-yet-migrated rules still make, and the corpus
# tape, which derives its replay reprojection from these same tuples (see
# `scripts/scoring_corpus/tape.py`). Adding a column is one edit, in one file.
# ---------------------------------------------------------------------------

INVOICE_HEADER_COLUMNS = (
    "id",
    "org_id",
    "vendor_id",
    "invoice_no",
    "invoice_date",
    "due_date",
    "total",
)

INVOICE_LINE_COLUMNS = (
    "id",
    "invoice_id",
    "sku",
    "desc",
    "qty",
    "unit_price",
    "line_total",
)

# In a joined row the header and the line share one namespace, so the columns
# whose names would collide are aliased. The line's `invoice_id` is not selected
# at all — the header's aliased `id` already carries the same value.
JOINED_HEADER_ALIASES = {"id": "invoice_id", "total": "invoice_total"}
JOINED_LINE_ALIASES = {"id": "line_id"}


def _quoted(column: str) -> str:
    # `desc` is a reserved word; the rest need no quoting.
    return f'"{column}"' if column == "desc" else column


def _select_list(
    prefix: Optional[str],
    columns: tuple,
    aliases: Optional[Dict[str, str]] = None,
) -> str:
    """Render one SELECT list from the column tuples above.

    Composed from module constants only — no caller input reaches it — so this
    builds SQL text without building an injection surface.
    """
    aliases = aliases or {}
    parts = []
    for column in columns:
        ref = f"{prefix}.{_quoted(column)}" if prefix else _quoted(column)
        alias = aliases.get(column)
        parts.append(f"{ref} AS {alias}" if alias else ref)
    return ",\n          ".join(parts)


_JOINED_COLUMNS = (
    _select_list("i", INVOICE_HEADER_COLUMNS, JOINED_HEADER_ALIASES)
    + ",\n          "
    + _select_list(
        "il",
        tuple(c for c in INVOICE_LINE_COLUMNS if c != "invoice_id"),
        JOINED_LINE_ALIASES,
    )
)


# ---------------------------------------------------------------------------
# Async reads
#
# Everything above is sync, taking the worker's `Connection`. The three below
# are async because their callers — the scoring gathering adapter, and the rules
# that have not crossed the seam yet — run on an async connection. The
# sync/async split is about who calls; where the SQL lives is not negotiable
# either way, and it lives here.
# ---------------------------------------------------------------------------

# Fetches one invoice's header fields, scoped to an org. Returns None if no such
# invoice exists in that org.
async def get_invoice_header(db: Any, *, org_id: str, invoice_id: str) -> Optional[Dict[str, Any]]:
    query = f"""
        SELECT
          {_select_list(None, INVOICE_HEADER_COLUMNS)}
        FROM invoices
        WHERE org_id = %(org_id)s
          AND id = %(invoice_id)s;
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"org_id": org_id, "invoice_id": invoice_id})
        return await cur.fetchone()


# Fetches every line on one invoice. Not org-scoped in the SQL: `invoice_lines`
# has no org_id column and its RLS policy scopes it through the parent invoice.
#
# Deliberately unordered, which is worth explaining because it looks like an
# oversight. Two per-line rules raise one alert per offending line, so line order
# decides alert order. There is no column that reproduces the order the rules see
# today: `invoice_lines` has no ordinal and no timestamp, and its `id` is a random
# UUID, so `ORDER BY id` would be deterministic but would deterministically differ
# from today's order on every multi-line invoice. Leaving it unordered matches the
# unordered join this replaces. A real fix needs a line-ordinal column, which is a
# schema change and belongs in its own ticket (#26).
async def get_invoice_lines(db: Any, *, invoice_id: str) -> List[Dict[str, Any]]:
    query = f"""
        SELECT
          {_select_list(None, INVOICE_LINE_COLUMNS)}
        FROM invoice_lines
        WHERE invoice_id = %(invoice_id)s;
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"invoice_id": invoice_id})
        return await cur.fetchall()


# Fetches one invoice joined to its lines, one flat row per line, scoped to an
# org. This is the pre-seam read: the rules that still hold a connection take
# their header fields off the first row and iterate the rest. `unit_price_delta`
# does not use it — it reads the same data off the snapshot — and the last
# caller goes away when the remaining rules cross the seam.
async def get_invoice_joined_rows(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[Dict[str, Any]]:
    query = f"""
        SELECT
          {_JOINED_COLUMNS}
        FROM invoices AS i
        JOIN invoice_lines AS il
          ON il.invoice_id = i.id
        WHERE i.org_id = %(org_id)s
          AND i.id = %(invoice_id)s;
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"org_id": org_id, "invoice_id": invoice_id})
        return await cur.fetchall()
