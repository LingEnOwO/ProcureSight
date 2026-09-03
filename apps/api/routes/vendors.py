from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List
from psycopg import Connection

from ..deps import org_conn
from ..models.vendor import Vendor
from ..repos.vendors import list_vendors as repo_list_vendors, get_vendor

router = APIRouter(prefix="/vendors", tags=["vendors"])


# List all vendors
@router.get("", response_model=List[Vendor])
def list_vendors(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(org_conn),
):
    return repo_list_vendors(conn, limit=limit, offset=offset)


# Get single vendor
@router.get("/{vendor_id}", response_model=Vendor)
def get_vendor_by_id(
    vendor_id: str,
    conn: Connection = Depends(org_conn),
):
    vendor = get_vendor(conn, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendor
