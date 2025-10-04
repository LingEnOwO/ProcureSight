from psycopg_pool import ConnectionPool
import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(".env.local")
class Settings(BaseSettings):
    DATABASE_URL: str
    
settings = Settings()
pool = ConnectionPool(conninfo=settings.DATABASE_URL, min_size=1, max_size=10)
def insert_raw_doc(*, org_id, s3_key, filename, mime, byte_len, uploaded_by=None):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_docs (org_id, s3_key, filename, mime, bytes, uploaded_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (org_id, s3_key, filename, mime, byte_len, uploaded_by),
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