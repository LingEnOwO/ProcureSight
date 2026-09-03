from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from apps.api.auth import get_user_context, UserContext
from apps.api.deps import org_aconn
from apps.api.models.alert import AlertCandidate
from apps.api.services.anomaly_scoring import score_invoice

router = APIRouter(prefix="/score", tags=["scoring"])


@router.post("/invoice/{invoice_id}")
async def debug_score_invoice(
    invoice_id: str,
    aconn: AsyncConnection = Depends(org_aconn),
    user_ctx: UserContext = Depends(get_user_context),
) -> Dict[str, Any]:
    """
    Debug endpoint: re-run anomaly scoring for an existing invoice.

    This endpoint does NOT modify the invoice itself. For now, it also does not
    persist new alerts to the `alerts` table; instead it returns the raw
    AlertCandidates so developers can inspect how the scoring behaves.

    Typical use cases:
      - After adjusting scoring thresholds or feature views.
      - After backfilling historical data.
      - When investigating why a particular invoice was or was not flagged.

    Test with curl (get IDs from the DB — see queries below):
      curl -s -X POST http://localhost:8000/score/invoice/<invoice_id> \
        -H "X-Org-Id: <org_id>" \
        -H "X-Business-User-Id: <user_id>" \
        -H "X-User-Role: admin" | jq

    Lookup queries:
      SELECT id, org_id FROM invoices LIMIT 10;
      SELECT id FROM users WHERE email = 'uploader@demo.local';
    """
    alerts: List[AlertCandidate] = await score_invoice(
        aconn,
        org_id=user_ctx.org_id,
        invoice_id=str(invoice_id),
    )

    # Convert dataclass instances to plain dicts so they are JSON-serializable.
    alerts_payload: List[Dict[str, Any]] = [asdict(alert) for alert in alerts]

    return {
        "ok": True,
        "org_id": user_ctx.org_id,
        "invoice_id": str(invoice_id),
        "alert_count": len(alerts_payload),
        "alerts": alerts_payload,
    }
