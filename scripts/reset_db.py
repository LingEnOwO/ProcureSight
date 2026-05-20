"""
Reset the database and MinIO back to a clean post-seed state.

Truncates all invoice/vendor/alert data while keeping the Demo Org and
Demo User fixtures created by `make seed`.  Also purges all uploaded
objects from the MinIO bucket so the SHA-256 dedup index stays consistent.

Usage:
    source venv/bin/activate
    python scripts/reset_db.py

Flags:
    --db-only    Skip MinIO cleanup
    --minio-only Skip DB truncation
    --yes        Skip confirmation prompt
"""

import argparse
import os
import sys

import boto3
import psycopg
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv(".env.local")

DB_URL        = os.getenv("DATABASE_URL",  "postgresql://procure:procure@localhost:5432/procuresight")
S3_ENDPOINT   = os.getenv("S3_ENDPOINT",   "http://localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
S3_BUCKET     = os.getenv("S3_BUCKET",     "procuresight")

# Leaf-to-root order so FK constraints don't block individual DELETEs;
# TRUNCATE … CASCADE makes this order redundant but keeps intent explicit.
TABLES = [
    "invoice_lines",
    "extractions",
    "alerts",
    "audit_log",
    "invoices",
    "vendor_contracts",
    "raw_docs",
    "vendors",
    "doc_chunks",
]


def reset_db() -> None:
    table_list = ", ".join(TABLES)
    sql = f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    print(f"[db]    truncated {len(TABLES)} tables, sequences reset")


def reset_minio() -> None:
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )

    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except ClientError:
        print(f"[minio] bucket '{S3_BUCKET}' not found — nothing to clean")
        return

    paginator = s3.get_paginator("list_objects_v2")
    keys = [
        obj["Key"]
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="org/")
        for obj in page.get("Contents", [])
    ]

    if not keys:
        print("[minio] no objects found under org/ prefix")
        return

    # delete_objects accepts at most 1 000 keys per call
    deleted = 0
    for i in range(0, len(keys), 1000):
        batch = [{"Key": k} for k in keys[i : i + 1000]]
        s3.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": batch})
        deleted += len(batch)

    print(f"[minio] deleted {deleted} object(s) from bucket '{S3_BUCKET}'")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-only",    action="store_true", help="Skip MinIO cleanup")
    parser.add_argument("--minio-only", action="store_true", help="Skip DB truncation")
    parser.add_argument("--yes", "-y",  action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if not args.yes:
        answer = input(
            "This will DELETE all invoices, vendors, alerts, and MinIO uploads.\n"
            "The Demo Org and Demo User will be preserved.\n"
            "Continue? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    if not args.minio_only:
        reset_db()

    if not args.db_only:
        reset_minio()

    print("Done — ready for a fresh upload run.")


if __name__ == "__main__":
    main()
