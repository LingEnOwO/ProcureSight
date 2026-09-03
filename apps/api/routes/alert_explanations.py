from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from psycopg import Connection

from ..auth import get_user_context, UserContext
from ..deps import org_conn
from ..services.rag_explainer import explain_alert, SUPPORTED_TYPES
from fastapi import Depends


router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/{alert_id}/explanation")
def get_alert_explanation(
    alert_id: str,
    conn: Connection = Depends(org_conn),
    user_ctx: UserContext = Depends(get_user_context),
) -> Dict[str, Any]:
    """Retrieve (or lazily generate) a cached explanation for an alert.

    Returns immediately if an explanation exists; generates one otherwise.
    """
    try:
        result = explain_alert(conn, user_ctx.org_id, alert_id, force=False)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    return result


@router.post("/{alert_id}/explain")
def explain_alert_endpoint(
    alert_id: str,
    force: bool = Query(False, description="Regenerate even if a cached explanation exists"),
    conn: Connection = Depends(org_conn),
    user_ctx: UserContext = Depends(get_user_context),
) -> Dict[str, Any]:
    """Generate (or return cached) an evidence-backed explanation for an alert.

    Supported alert types: unit_price_delta, vendor_volume_spike, duplicate_invoice.
    Pass ?force=true to regenerate an existing explanation.
    """
    try:
        result = explain_alert(conn, user_ctx.org_id, alert_id, force=force)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return result
