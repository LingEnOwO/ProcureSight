from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from psycopg import Connection, connect
from pydantic import BaseModel

from ..repos.alerts import list_alerts_for_org, update_alert_status
from ..settings import settings


router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertUpdatePayload(BaseModel):
    """Payload for acknowledging or dismissing an alert.

    For v1 we keep this intentionally simple:
      - callers must always supply a new `status` value (e.g. "open",
        "acknowledged", "dismissed").
      - the backend derives `acknowledged_at` automatically whenever an
        alert moves out of the "open" state.
    """

    status: str
    acknowledged_by: Optional[str] = None


@router.get("/")
def list_alerts(
    status: Optional[str] = Query(None, description="Filter by alert status"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    limit: int = Query(50, ge=1, le=100, description="Max number of alerts"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> Dict[str, Any]:
    """List alerts for the current org with optional filtering.

    Always scopes results to the current org (derived from settings.ORG_ID).
    """
    org_id = settings.ORG_ID
    if not org_id:
        raise HTTPException(status_code=400, detail="Missing org context")

    conn: Connection = connect(settings.DATABASE_URL)
    try:
        with conn:
            items = list_alerts_for_org(
                conn,
                org_id=str(org_id),
                status=status,
                severity=severity,
                limit=limit,
                offset=offset,
            )
    finally:
        conn.close()

    return {
        "items": items,
        "limit": limit,
        "offset": offset,
    }


@router.patch("/{alert_id}")
def patch_alert(alert_id: str, payload: AlertUpdatePayload) -> Dict[str, Any]:
    """Update an alert's status / acknowledgement fields.

    This is used by the UI to acknowledge or dismiss alerts. The org scope is
    enforced by always including the current org_id in the update query.
    """
    org_id = settings.ORG_ID
    if not org_id:
        raise HTTPException(status_code=400, detail="Missing org context")

    conn: Connection = connect(settings.DATABASE_URL)
    try:
        with conn:
            updated = update_alert_status(
                conn,
                org_id=str(org_id),
                alert_id=alert_id,
                status=payload.status,
                acknowledged_by=payload.acknowledged_by,
            )
    finally:
        conn.close()

    if updated is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    return updated