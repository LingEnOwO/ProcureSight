import os, psycopg
from dotenv import load_dotenv

load_dotenv(".env.local")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight")
ddl = """
create table if not exists raw_docs (
    id bigSerial primary key,
    filename text not null,
    s3_uri text not null,
    content_type text,
    size_bytes bigint,
    checksum_sha256 text,
    uploaded_at timestamptz default now()
);
"""
with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(ddl)
        conn.commit()
print("[ok] schema ready")
