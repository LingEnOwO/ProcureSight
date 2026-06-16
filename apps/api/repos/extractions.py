import json
from typing import Optional


def insert_extraction(
    conn,
    *,
    raw_doc_id: int,
    invoice_id: str,
    confidence: float,
    field_confidence: dict,
    warnings: list,
    needs_review: bool,
) -> None:
    status = "needs_review" if needs_review else "ok"
    payload = json.dumps({"field_confidence": field_confidence, "warnings": warnings})
    conn.execute(
        """
        INSERT INTO extractions (raw_doc_id, invoice_id, status, confidence, needs_review, payload_json)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (raw_doc_id, invoice_id, status, confidence, needs_review, payload),
    )
