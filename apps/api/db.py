from psycopg_pool import ConnectionPool
from psycopg import sql
from databases import Database

from apps.api.settings import settings

pool = ConnectionPool(conninfo=settings.DATABASE_URL, min_size=1, max_size=10)

# Async DB handle (used by async routes/services, e.g. anomaly scoring).
# This can coexist with the sync psycopg pool while we incrementally migrate.
database = Database(settings.DATABASE_URL)


async def connect_database() -> None:
    """Connect the async Database pool on FastAPI startup."""
    if not database.is_connected:
        await database.connect()


async def disconnect_database() -> None:
    """Disconnect the async Database pool on FastAPI shutdown."""
    if database.is_connected:
        await database.disconnect()

def get_raw_doc_by_hash(*, org_id: str, sha256: str):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SET LOCAL app.org_id = {}").format(sql.Literal(org_id)))
        cur.execute(
            """
            SELECT id, s3_key FROM raw_docs WHERE org_id = %s AND sha256 = %s LIMIT 1
            """,
            (org_id, sha256)
        )
        row = cur.fetchone()
        if row:
            return {"id": row[0], "s3_key": row[1]}
        return None

def insert_raw_doc(*, org_id, s3_key, filename, mime, byte_len, sha256, uploaded_by=None):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SET LOCAL app.org_id = {}").format(sql.Literal(org_id)))
        if uploaded_by:
            cur.execute(sql.SQL("SET LOCAL app.actor_id = {}").format(sql.Literal(uploaded_by)))
        cur.execute(
            """
            INSERT INTO raw_docs (org_id, s3_key, filename, mime, bytes, sha256, uploaded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (org_id, s3_key, filename, mime, byte_len, sha256, uploaded_by),
        )
        (raw_doc_id, ) = cur.fetchone()
        conn.commit()
        return raw_doc_id
    
def db_ok() -> bool:
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute('select 1;')
            cur.fetchone()
        return True
    except Exception:
        return False