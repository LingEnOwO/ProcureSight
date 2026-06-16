#!/usr/bin/env python3
"""
Index contract and policy documents into doc_chunks for vector search.

Usage:
    python scripts/index_documents.py \\
        --contracts-dir dataset/generated/contracts \\
        --policies-dir  dataset/generated/policies \\
        --org-id        <uuid>

If --org-id is omitted the script uses the Demo Org from the database.

The operation is idempotent: re-running will update existing chunks in place.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))

from apps.api.services.doc_indexer import index_documents


def resolve_demo_org(conn: psycopg.Connection) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM orgs WHERE name = 'Demo Org' LIMIT 1")
        row = cur.fetchone()
        return str(row[0]) if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Index contracts/policies into doc_chunks.")
    parser.add_argument("--contracts-dir", default=None, help="Path to contracts directory")
    parser.add_argument("--policies-dir", default=None, help="Path to policies directory")
    parser.add_argument("--org-id", default=None, help="Organisation UUID (uses Demo Org if omitted)")
    parser.add_argument("--chunk-size", type=int, default=400, help="Target chars per chunk (default 400)")
    parser.add_argument("--overlap", type=int, default=80, help="Overlap chars between chunks (default 80)")
    args = parser.parse_args()

    if not args.contracts_dir and not args.policies_dir:
        sys.exit("Provide at least one of --contracts-dir or --policies-dir.")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL environment variable is not set.")

    with psycopg.connect(db_url) as conn:
        org_id = args.org_id or resolve_demo_org(conn)
        if not org_id:
            sys.exit("Could not find Demo Org in database. Pass --org-id explicitly.")

        print(f"Indexing for org_id={org_id}")

        total = {"indexed": 0, "files": 0}

        if args.contracts_dir:
            print(f"\nContracts: {args.contracts_dir}")
            result = index_documents(
                conn,
                org_id,
                args.contracts_dir,
                source_type="contract",
                chunk_size=args.chunk_size,
                overlap=args.overlap,
            )
            total["indexed"] += result["indexed"]
            total["files"] += result["files"]

        if args.policies_dir:
            print(f"\nPolicies: {args.policies_dir}")
            result = index_documents(
                conn,
                org_id,
                args.policies_dir,
                source_type="policy",
                chunk_size=args.chunk_size,
                overlap=args.overlap,
            )
            total["indexed"] += result["indexed"]
            total["files"] += result["files"]

        print(f"\nDone. {total['files']} files, {total['indexed']} chunks indexed.")


if __name__ == "__main__":
    main()
