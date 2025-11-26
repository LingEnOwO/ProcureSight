import json
from typing import Iterable

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