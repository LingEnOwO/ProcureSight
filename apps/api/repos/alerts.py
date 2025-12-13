import json
from typing import Iterable, Any, Dict, List, Optional
from psycopg import Connection

from apps.api.services.anomaly_scoring import AlertCandidate


def insert_alert_candidates(conn: Connection, candidates: Iterable[AlertCandidate]) -> None:
    """
    Persist scored alerts into the `alerts` table.

    This is a thin repo-layer helper so that routes/services do not have to
    embed INSERT statements directly.

    Parameters
    ----------
    conn:
        psycopg Connection with an active transaction (typically inside a
        `with conn:` block in the caller).
    candidates:
        Iterable of AlertCandidate objects produced by the anomaly scoring
        service. If empty, this function is a no-op.
    """
    candidates = list(candidates)
    if not candidates:
        return

    with conn.cursor() as cur:
        for cand in candidates:
            cur.execute(
                """
                INSERT INTO alerts (
                  org_id,
                  vendor_id,
                  invoice_id,
                  type,
                  severity,
                  message,
                  meta_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    cand.org_id,
                    cand.vendor_id,
                    cand.invoice_id,
                    cand.type,
                    cand.severity,
                    cand.message,
                    json.dumps(cand.meta),
                ),
            )

def list_alerts_for_org(
    conn: Connection,
    *,
    org_id: str,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Return a list of alerts for the given org with optional filters.

    Results are ordered by created_at DESC and support simple limit/offset
    pagination.
    """
    query = """
        SELECT
          id,
          org_id,
          invoice_id,
          vendor_id,
          type,
          severity,
          resolved,
          message,
          meta_json,
          created_at,
          acknowledged_at,
          acknowledged_by,
          CASE
            WHEN resolved THEN 'resolved'
            ELSE 'open'
          END AS status
        FROM alerts
        WHERE org_id = %s
    """
    params: List[Any] = [org_id]

    if status is not None:
        # Map textual status to the underlying resolved flag.
        # For v1 we treat anything other than "open" as resolved.
        if status == "open":
            query += " AND resolved = FALSE"
        else:
            query += " AND resolved = TRUE"
    if severity is not None:
        query += " AND severity = %s"
        params.append(severity)

    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
        columns = [col[0] for col in cur.description]

    return [dict(zip(columns, row)) for row in rows]


def update_alert_status(
    conn: Connection,
    *,
    org_id: str,
    alert_id: str,
    status: str,
    acknowledged_by: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Update an alert's status and acknowledgement fields.

    When status moves out of "open", acknowledged_at is set to NOW(). When the status is open, we set it to Null because no one takes care of the alert.
    """
    if status == "open":
        is_open = True
    else:
        is_open = False

    resolved_value = not is_open

    query = """
        UPDATE alerts
        SET
          resolved = %s,
          acknowledged_at = CASE WHEN %s THEN NULL ELSE NOW() END,
          acknowledged_by = %s
        WHERE org_id = %s
          AND id = %s
        RETURNING
          id,
          org_id,
          invoice_id,
          vendor_id,
          type,
          severity,
          resolved,
          message,
          meta_json,
          created_at,
          acknowledged_at,
          acknowledged_by,
          CASE
            WHEN resolved THEN 'resolved'
            ELSE 'open'
          END AS status;
    """

    params: List[Any] = [
        resolved_value,
        is_open,
        acknowledged_by,
        org_id,
        alert_id,
    ]

    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        if row is None:
            return None
        columns = [col[0] for col in cur.description]

    return dict(zip(columns, row))