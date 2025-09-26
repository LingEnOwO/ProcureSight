import os, sys, mimetypes, hashlib, pathlib, boto3, psycopg
from dotenv import load_dotenv

load_dotenv(".env.local")
ROOT = pathlib.Path(sys.argv[1]).resolve()
DB = os.getenv("DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY","minioadmin")
S3_BUCKET = os.getenv("S3_BUCKET","procuresight")

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
)

# ensure bucket exists
try:
    s3.head_bucket(Bucket=S3_BUCKET)
except Exception:
    s3.create_bucket(Bucket=S3_BUCKET)

def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

rows = []
for p in ROOT.rglob("*"):
    if not p.is_file(): continue
    key = f"samples/{p.relative_to(ROOT)}"
    s3.upload_file(str(p), S3_BUCKET, key)
    uri = f"s3://{S3_BUCKET}/{key}"
    ctype, _ = mimetypes.guess_type(p.name)
    rows.append((p.name, uri, ctype, p.stat().st_size, sha256(p)))

with psycopg.connect(DB) as conn, conn.cursor() as cur:
    cur.executemany(
        "insert into raw_docs (filename, s3_uri, content_type, size_bytes, checksum_sha256) values (%s,%s,%s,%s,%s)",
        rows,
    )
    conn.commit()
print(f"[ok] uploaded {len(rows)} files and registered rows in raw_docs")