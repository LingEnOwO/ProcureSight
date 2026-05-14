from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from ..auth import get_user_context, UserContext
from ..db import pool
from ..services.rag_explainer import explain_alert, SUPPORTED_TYPES
from fastapi import Depends


router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/{alert_id}/explanation")
def get_alert_explanation(
    alert_id: str,
    user_ctx: UserContext = Depends(get_user_context),
) -> Dict[str, Any]:
    """Retrieve (or lazily generate) a cached explanation for an alert.

    Returns immediately if an explanation exists; generates one otherwise.
    """
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", (user_ctx.org_id,))
            cur.execute("SELECT set_config('app.actor_id', %s, true)", (user_ctx.business_user_id,))
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
    user_ctx: UserContext = Depends(get_user_context),
) -> Dict[str, Any]:
    """Generate (or return cached) an evidence-backed explanation for an alert.

    Supported alert types: unit_price_delta, vendor_volume_spike, duplicate_invoice.
    Pass ?force=true to regenerate an existing explanation.
    """
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", (user_ctx.org_id,))
            cur.execute("SELECT set_config('app.actor_id', %s, true)", (user_ctx.business_user_id,))
        try:
            result = explain_alert(conn, user_ctx.org_id, alert_id, force=force)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                raise HTTPException(status_code=404, detail=msg)
            raise HTTPException(status_code=400, detail=msg)

    return result
