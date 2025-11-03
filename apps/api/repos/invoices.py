from typing import Optional, List, Dict, Any
from psycopg import Connection
from decimal import Decimal

# Ensures that a vendor record exists for a given organization and returns its ID.
# Avoids duplicate vendor creation by using ON CONFLICT to upsert.
def ensure_vendor(conn: Connection, org_id: str, name: str) -> str:
    sql = """
    INSERT INTO vendors (id, org_id, name, created_at)
    VALUES (gen_random_uuid(), %(org_id)s, %(name)s, now())
    ON CONFLICT (org_id, name) DO UPDATE SET name = EXCLUDED.name
    RETURNING id;
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"org_id": org_id, "name": name})
        return cur.fetchone()[0] # Returns the vendor’s UUID 

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
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, vendor_id, invoice_no, invoice_date, due_date, currency, subtotal, tax, total, status
            FROM invoices
            ORDER BY invoice_date DESC, created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        columns = [col[0] for col in cur.description] # DB metadata
        return [dict(zip(columns, row)) for row in cur.fetchall()]


# Fetches a single invoice and its line items. Returns None if not found.
def get_invoice_with_lines(conn: Connection, invoice_id: str) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, vendor_id, invoice_no, invoice_date, due_date, currency, subtotal, tax, total, status
            FROM invoices WHERE id = %s
            """,
            (invoice_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [c[0] for c in cur.description]
        inv = dict(zip(columns, row))

        cur.execute(
            """
            SELECT id, sku, "desc", qty, unit_price, line_total
            FROM invoice_lines WHERE invoice_id = %s ORDER BY id
            """,
            (invoice_id,),
        )
        line_cols = [c[0] for c in cur.description]
        inv["lines"] = [dict(zip(line_cols, r)) for r in cur.fetchall()]
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