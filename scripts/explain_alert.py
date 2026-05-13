#!/usr/bin/env python3
"""
Manual test script for the RAG explanation system.

Usage:
    python scripts/explain_alert.py --alert-id <uuid> [--force] [--org-id <uuid>]

If --org-id is omitted, the script fetches the alert's org from the DB directly
(useful for quick local testing where org_id is unknown).
"""
import argparse
import json
import os
import sys

# Ensure the project root is on PYTHONPATH
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))

from apps.api.services.rag_explainer import explain_alert


def resolve_org_id(conn: psycopg.Connection, alert_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT org_id FROM alerts WHERE id = %s", (alert_id,))
        row = cur.fetchone()
        return str(row[0]) if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a RAG explanation for an alert.")
    parser.add_argument("--alert-id", required=True, help="UUID of the alert to explain")
    parser.add_argument("--org-id", default=None, help="Organisation UUID (auto-detected if omitted)")
    parser.add_argument("--force", action="store_true", help="Regenerate even if explanation is cached")
    args = parser.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL environment variable is not set.")

    with psycopg.connect(db_url) as conn:
        org_id = args.org_id or resolve_org_id(conn, args.alert_id)
        if not org_id:
            sys.exit(f"Alert {args.alert_id} not found in database.")

        # Set the org GUC so RLS policies pass
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))

        print(f"Explaining alert {args.alert_id} (org={org_id}, force={args.force})\n")

        try:
            result = explain_alert(conn, org_id, args.alert_id, force=args.force)
        except ValueError as exc:
            sys.exit(str(exc))

    print("=" * 60)
    print(f"Alert type : {result['alert_type']}")
    print(f"Severity   : {result['severity']}")
    print(f"Cached     : {result['cached']}")
    print()
    print(result["explanation"])
    print()
    print("LLM output (raw):")
    print(json.dumps(result["llm_output"], indent=2))
    print()
    print("Evidence metrics:")
    print(json.dumps(result["evidence"]["metrics"], indent=2, default=str))


if __name__ == "__main__":
    main()
