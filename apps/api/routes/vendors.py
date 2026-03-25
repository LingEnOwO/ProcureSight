from fastapi import APIRouter, HTTPException, Query, Depends
from psycopg import connect
from typing import List

from ..settings import settings
from ..auth import get_user_context, UserContext
from ..models.vendor import Vendor
from ..repos.vendors import list_vendors as repo_list_vendors, get_vendor

router = APIRouter(prefix="/vendors", tags=["vendors"])


def get_conn(user_ctx: UserContext):
    """Create database connection with RLS context set from authenticated user."""
    conn = connect(settings.app_db_url)
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, true)", (user_ctx.org_id,))
    return conn

# List all vendors 
@router.get("", response_model=List[Vendor])
def list_vendors(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_ctx: UserContext = Depends(get_user_context)
):
    conn = get_conn(user_ctx)
    try:
        return repo_list_vendors(conn, limit=limit, offset=offset)
    finally:
        conn.close()

# Get single vendor 
@router.get("/{vendor_id}", response_model=Vendor)
def get_vendor_by_id(
    vendor_id: str,
    user_ctx: UserContext = Depends(get_user_context)
):
    conn = get_conn(user_ctx)
    try:
        vendor = get_vendor(conn, vendor_id)
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return vendor
    finally:
        conn.close()