import json
from typing import Any, Dict, Optional
from psycopg import Connection


def get_alert(conn: Connection, org_id: str, alert_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single alert scoped to the given org. Returns None if not found."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              a.id,
              a.org_id,
              a.invoice_id,
              a.vendor_id,
              a.type,
              a.severity,
              a.message,
              a.meta_json,
              a.created_at,
              a.resolved,
              a.explanation_text,
              a.explanation_json,
              a.explanation_generated_at,
              v.name AS vendor_name
            FROM alerts a
            LEFT JOIN vendors v ON v.id = a.vendor_id
            WHERE a.id = %s AND a.org_id = %s
            """,
            (alert_id, org_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        columns = [c[0] for c in cur.description]
        return dict(zip(columns, row))


def save_explanation(
    conn: Connection,
    org_id: str,
    alert_id: str,
    explanation_text: str,
    explanation_json: Dict[str, Any],
) -> None:
    """Persist the generated explanation back onto the alerts row."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE alerts
            SET
              explanation_text = %s,
              explanation_json = %s,
              explanation_generated_at = now()
            WHERE id = %s AND org_id = %s
            """,
            (explanation_text, json.dumps(explanation_json), alert_id, org_id),
        )
