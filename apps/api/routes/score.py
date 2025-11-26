from dataclasses import asdict
from typing import Any, Dict, List

from databases import Database
from fastapi import APIRouter, HTTPException

from apps.api.services.anomaly_scoring import AlertCandidate, score_invoice
from apps.api.settings import settings

router = APIRouter(prefix="/score", tags=["scoring"])


@router.post("/invoice/{invoice_id}")
async def debug_score_invoice(invoice_id: str) -> Dict[str, Any]:
    """
    Debug endpoint: re-run anomaly scoring for an existing invoice.

    This endpoint does NOT modify the invoice itself. For now, it also does not
    persist new alerts to the `alerts` table; instead it returns the raw
    AlertCandidates so developers can inspect how the scoring behaves.

    Typical use cases:
      - After adjusting scoring thresholds or feature views.
      - After backfilling historical data.
      - When investigating why a particular invoice was or was not flagged.
    """
    org_id = settings.ORG_ID
    if not org_id:
        raise HTTPException(status_code=400, detail="Missing org context")

    # Run scoring against the existing DB state using a temporary Database
    # instance. This keeps the debug endpoint self-contained and avoids
    # coupling it to any particular connection pool implementation.
    db = Database(settings.DATABASE_URL)
    await db.connect()
    try:
        alerts: List[AlertCandidate] = await score_invoice(
            db,
            org_id=str(org_id),
            invoice_id=str(invoice_id),
        )
    finally:
        await db.disconnect()

    # Convert dataclass instances to plain dicts so they are JSON-serializable.
    alerts_payload: List[Dict[str, Any]] = [asdict(alert) for alert in alerts]

    return {
        "ok": True,
        "org_id": str(org_id),
        "invoice_id": str(invoice_id),
        "alert_count": len(alerts_payload),
        "alerts": alerts_payload,
    }