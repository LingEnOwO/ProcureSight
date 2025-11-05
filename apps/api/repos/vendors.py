from typing import List, Dict, Any, Optional
from psycopg import Connection

# Lists vendors for the current org context with pagination.
# Org scoping should be enforced via RLS using app.org_id GUC.
def list_vendors(conn: Connection, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name
            FROM vendors
            ORDER BY name ASC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        columns = [c[0] for c in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

# Fetches a single vendor by ID. Returns None if not found.
def get_vendor(conn: Connection, vendor_id: str) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name
            FROM vendors
            WHERE id = %s
            """,
            (vendor_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [c[0] for c in cur.description]
        return dict(zip(columns, row))