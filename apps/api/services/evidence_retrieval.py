"""
Structured evidence retrieval for the RAG explanation system.

Each function retrieves SQL-based evidence for a specific alert type and
returns a typed dict. Future retrieval sources (contracts, pgvector, policies)
can be added here as additional functions without touching the orchestrator.
"""
from typing import Any, Dict, List, Optional
from psycopg import Connection

from ..repos.invoices import get_invoice_with_lines


def retrieve_unit_price_delta(conn: Connection, alert: Dict[str, Any]) -> Dict[str, Any]:
    meta = alert.get("meta_json") or {}
    vendor_id = alert.get("vendor_id") or meta.get("vendor_id")
    invoice_id = alert.get("invoice_id") or meta.get("invoice_id")
    sku = meta.get("sku")
    desc = meta.get("desc")
    line_id = meta.get("line_id")

    current_invoice = get_invoice_with_lines(conn, invoice_id) if invoice_id else None

    # Find the specific triggering line from the loaded invoice
    current_line: Optional[Dict[str, Any]] = None
    if current_invoice and line_id:
        for ln in current_invoice.get("lines", []):
            if str(ln.get("id")) == str(line_id):
                current_line = ln
                break
    if current_line is None and current_invoice:
        for ln in current_invoice.get("lines", []):
            if (sku and ln.get("sku") == sku) or (desc and ln.get("desc") == desc):
                current_line = ln
                break

    # Historical lines: same vendor + matching sku/desc, excluding current invoice
    historical_lines: List[Dict[str, Any]] = []
    if vendor_id and (sku or desc):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  il.id,
                  il.sku,
                  il."desc",
                  il.qty,
                  il.unit_price,
                  il.line_total,
                  i.invoice_no,
                  i.invoice_date,
                  i.id AS invoice_id
                FROM invoice_lines il
                JOIN invoices i ON i.id = il.invoice_id
                WHERE i.org_id = %s
                  AND i.vendor_id = %s
                  AND (%s::text IS NULL OR il.sku = %s::text)
                  AND (%s::text IS NULL OR il."desc" = %s::text)
                  AND i.id != %s
                ORDER BY i.invoice_date DESC
                LIMIT 10
                """,
                (
                    alert["org_id"], vendor_id,
                    sku, sku,
                    desc, desc,
                    invoice_id or "00000000-0000-0000-0000-000000000000",
                ),
            )
            cols = [c[0] for c in cur.description]
            historical_lines = [dict(zip(cols, r)) for r in cur.fetchall()]

    return {
        "current_invoice": current_invoice,
        "current_line": current_line,
        "vendor_name": alert.get("vendor_name"),
        "historical_lines": historical_lines,
        "metrics": {
            "unit_price": meta.get("unit_price"),
            "median_unit_price": meta.get("median_unit_price"),
            "ratio": meta.get("ratio"),
            "sample_size": meta.get("sample_size"),
            "sku": sku,
            "desc": desc,
        },
    }


def retrieve_vendor_volume_spike(conn: Connection, alert: Dict[str, Any]) -> Dict[str, Any]:
    meta = alert.get("meta_json") or {}
    vendor_id = alert.get("vendor_id") or meta.get("vendor_id")
    invoice_id = alert.get("invoice_id") or meta.get("invoice_id")

    current_invoice = get_invoice_with_lines(conn, invoice_id) if invoice_id else None
    current_date = current_invoice.get("invoice_date") if current_invoice else None

    historical_invoices: List[Dict[str, Any]] = []
    if vendor_id:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  id,
                  invoice_no,
                  invoice_date,
                  total,
                  subtotal,
                  currency
                FROM invoices
                WHERE org_id = %s
                  AND vendor_id = %s
                  AND id != %s
                  AND (%s::date IS NULL OR invoice_date < %s::date)
                ORDER BY invoice_date DESC
                LIMIT 10
                """,
                (
                    alert["org_id"], vendor_id,
                    invoice_id or "00000000-0000-0000-0000-000000000000",
                    current_date, current_date,
                ),
            )
            cols = [c[0] for c in cur.description]
            historical_invoices = [dict(zip(cols, r)) for r in cur.fetchall()]

    counts = meta.get("counts") or {}
    baseline_window = meta.get("baseline_window", "30d")

    return {
        "current_invoice": current_invoice,
        "vendor_name": alert.get("vendor_name"),
        "historical_invoices": historical_invoices,
        "metrics": {
            "invoice_total": meta.get("invoice_total"),
            "baseline_median_total": meta.get("baseline_median_total"),
            "ratio": meta.get("ratio"),
            "baseline_window": baseline_window,
            "invoice_count": counts.get(f"invoice_count_{baseline_window}", counts.get("invoice_count_30d")),
        },
    }


def retrieve_duplicate_invoice(conn: Connection, alert: Dict[str, Any]) -> Dict[str, Any]:
    meta = alert.get("meta_json") or {}
    invoice_id = alert.get("invoice_id") or meta.get("invoice_id")

    current_invoice = get_invoice_with_lines(conn, invoice_id) if invoice_id else None

    # The canonical duplicate — prefer the first entry in duplicates[]
    duplicates_meta = meta.get("duplicates") or []
    candidate_id = meta.get("candidate_invoice_id")
    if not candidate_id and duplicates_meta:
        candidate_id = duplicates_meta[0].get("invoice_id")

    duplicate_invoice: Optional[Dict[str, Any]] = None
    if candidate_id:
        duplicate_invoice = get_invoice_with_lines(conn, candidate_id)

    # Fallback: search by same vendor + invoice_no if candidate_id missing
    if duplicate_invoice is None and current_invoice:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM invoices
                WHERE org_id = %s
                  AND vendor_id = %s
                  AND invoice_no = %s
                  AND id != %s
                LIMIT 1
                """,
                (
                    alert["org_id"],
                    current_invoice.get("vendor_id"),
                    current_invoice.get("invoice_no"),
                    invoice_id,
                ),
            )
            row = cur.fetchone()
            if row:
                duplicate_invoice = get_invoice_with_lines(conn, str(row[0]))

    # Determine which fields matched
    matched_fields: List[str] = []
    totals_match = False
    if duplicates_meta:
        match_on = duplicates_meta[0].get("match_on") or {}
        if match_on.get("invoice_no"):
            matched_fields.append("invoice_no")
        if match_on.get("total"):
            matched_fields.append("total")
            totals_match = True
    elif current_invoice and duplicate_invoice:
        if current_invoice.get("invoice_no") == duplicate_invoice.get("invoice_no"):
            matched_fields.append("invoice_no")
        if current_invoice.get("total") == duplicate_invoice.get("total"):
            matched_fields.append("total")
            totals_match = True

    return {
        "current_invoice": current_invoice,
        "duplicate_invoice": duplicate_invoice,
        "vendor_name": alert.get("vendor_name"),
        "matched_fields": matched_fields,
        "totals_match": totals_match,
    }


def retrieve_excessive_consulting(conn: Connection, alert: Dict[str, Any]) -> Dict[str, Any]:
    """Evidence for excessive_consulting alerts.

    Re-uses vector evidence already stored in meta_json during scoring.
    Falls back to a fresh vector search if meta is absent (e.g. older alerts).
    """
    meta = alert.get("meta_json") or {}
    invoice_id = alert.get("invoice_id") or meta.get("invoice_id")

    current_invoice = get_invoice_with_lines(conn, invoice_id) if invoice_id else None

    # Prefer pre-computed evidence from scoring; fall back to a fresh search.
    vector_evidence: List[Dict[str, Any]] = meta.get("vector_evidence") or []
    if not vector_evidence and invoice_id:
        from .vector_retrieval import search_chunks
        query = "consulting rate limit professional services cap hourly rate"
        raw = search_chunks(conn, alert["org_id"], query, source_types=["contract", "policy"])
        vector_evidence = [
            {
                "source_type": c["source_type"],
                "source_name": c["source_name"],
                "snippet": c["chunk_text"][:300],
                "similarity": float(c["similarity"]) if c.get("similarity") is not None else None,
            }
            for c in raw
        ]

    invoice_facts: Dict[str, Any] = {}
    if current_invoice:
        consulting_total = meta.get("consulting_total")
        consulting_lines = meta.get("consulting_lines") or []
        hours = sum(
            ln["qty"] for ln in consulting_lines if ln.get("qty") is not None
        )
        invoice_facts = {
            "vendor": alert.get("vendor_name") or current_invoice.get("vendor_name"),
            "invoice_no": current_invoice.get("invoice_no"),
            "invoice_date": str(current_invoice.get("invoice_date") or ""),
            "consulting_amount": f"${float(consulting_total):,.2f}" if consulting_total else "N/A",
            "consulting_hours": f"{hours:.1f}" if hours else "N/A",
        }

    return {
        "current_invoice": current_invoice,
        "vendor_name": alert.get("vendor_name"),
        "vector_evidence": vector_evidence,
        "invoice_facts": invoice_facts,
        "metrics": {
            "consulting_total": meta.get("consulting_total"),
            "contract_rate_found": meta.get("contract_rate_found"),
            "invoice_rate": meta.get("invoice_rate"),
        },
    }


def retrieve_evidence(conn: Connection, alert: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch to the appropriate evidence retriever based on alert type."""
    alert_type = alert.get("type", "")
    if alert_type == "unit_price_delta":
        return retrieve_unit_price_delta(conn, alert)
    if alert_type == "vendor_volume_spike":
        return retrieve_vendor_volume_spike(conn, alert)
    if alert_type == "duplicate_invoice":
        return retrieve_duplicate_invoice(conn, alert)
    if alert_type == "excessive_consulting":
        return retrieve_excessive_consulting(conn, alert)
    return {}
