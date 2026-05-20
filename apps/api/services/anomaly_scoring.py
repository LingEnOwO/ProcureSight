from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row

from apps.api.repos.contracts import get_vendor_contract
from apps.api.repos.invoice_stats import (
    get_vendor_sku_baseline_price,
    get_single_vendor_spend_stats,
)


# Simple container used by the pipeline to represent alerts that should be
# persisted into the `alerts` table. This keeps scoring logic separate from
# persistence so we can unit-test it easily.
@dataclass
class AlertCandidate:
    org_id: str
    invoice_id: str
    vendor_id: str
    type: str
    severity: str  # "low" | "medium" | "high" | "critical"
    message: str
    meta: Dict[str, Any]


# ── Unit price delta thresholds ──────────────────────────────────────────────
MIN_SAMPLE_SIZE_FOR_BASELINE = 5
LOW_PRICE_RATIO_THRESHOLD = 1.5     # 1.5x–2x  → "low"
MEDIUM_PRICE_RATIO_THRESHOLD = 2.0  # 2x–3x    → "medium"
HIGH_PRICE_RATIO_THRESHOLD = 3.0    # 3x+       → "high"

# ── Vendor volume spike thresholds ───────────────────────────────────────────
MIN_INVOICES_FOR_SPEND_BASELINE = 5
MEDIUM_TOTAL_RATIO_THRESHOLD = 2.0  # 2x–3x    → "medium"
HIGH_TOTAL_RATIO_THRESHOLD = 3.0    # 3x+       → "high"


async def _fetch_invoice_lines(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[Dict[str, Any]]:
    query = """
        SELECT
          i.id AS invoice_id,
          i.org_id,
          i.vendor_id,
          i.invoice_no,
          i.invoice_date,
          i.due_date,
          i.total AS invoice_total,
          il.id AS line_id,
          il.sku,
          il."desc",
          il.qty,
          il.unit_price,
          il.line_total
        FROM invoices AS i
        JOIN invoice_lines AS il
          ON il.invoice_id = i.id
        WHERE i.org_id = %(org_id)s
          AND i.id = %(invoice_id)s;
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"org_id": org_id, "invoice_id": invoice_id})
        return await cur.fetchall()


async def _score_unit_price_deltas_for_invoice(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[AlertCandidate]:
    """
    Rule: flag line items whose unit price is significantly higher than the
    historical median price for the same (org, vendor, sku[, desc]).

    Severity bands:
      low    — 1.5x–2x median
      medium — 2x–3x median
      high   — 3x+ median
    """
    rows = await _fetch_invoice_lines(db, org_id=org_id, invoice_id=invoice_id)
    if not rows:
        return []

    candidates: List[AlertCandidate] = []
    header = rows[0]
    vendor_id = header["vendor_id"]
    invoice_no = header["invoice_no"]

    for row in rows:
        line_id = row["line_id"]
        sku = row["sku"]
        desc = row["desc"]
        unit_price = row["unit_price"]

        if unit_price is None or sku is None:
            continue

        baseline = await get_vendor_sku_baseline_price(
            db,
            org_id=org_id,
            vendor_id=vendor_id,
            sku=sku,
            desc=desc,
        )
        if baseline is None:
            continue

        sample_size = baseline["sample_size"] or 0
        if sample_size < MIN_SAMPLE_SIZE_FOR_BASELINE:
            continue

        median_price: Optional[float] = baseline["median_unit_price"]
        if not median_price or median_price <= 0:
            continue

        ratio = float(unit_price) / float(median_price)

        severity: Optional[str] = None
        if ratio >= HIGH_PRICE_RATIO_THRESHOLD:
            severity = "high"
        elif ratio >= MEDIUM_PRICE_RATIO_THRESHOLD:
            severity = "medium"
        elif ratio >= LOW_PRICE_RATIO_THRESHOLD:
            severity = "low"

        if severity is None:
            continue

        message = (
            f"Unit price {unit_price:.2f} for SKU '{sku}' on invoice "
            f"{invoice_no or invoice_id} is {ratio:.2f}x the historical "
            f"median price ({median_price:.2f}) for this vendor."
        )

        meta: Dict[str, Any] = {
            "rule": "unit_price_delta_vs_median",
            "ratio": ratio,
            "median_unit_price": median_price,
            "unit_price": float(unit_price),
            "sample_size": sample_size,
            "sku": sku,
            "desc": desc,
            "invoice_no": invoice_no,
            "invoice_id": str(invoice_id),
            "vendor_id": str(vendor_id),
            "line_id": str(line_id),
        }

        candidates.append(
            AlertCandidate(
                org_id=str(org_id),
                invoice_id=str(invoice_id),
                vendor_id=str(vendor_id),
                type="unit_price_delta",
                severity=severity,
                message=message,
                meta=meta,
            )
        )

    return candidates


async def _find_potential_duplicate_invoices(
    db: Any,
    *,
    org_id: str,
    vendor_id: str,
    invoice_id: str,
    invoice_no: Optional[str],
) -> List[Dict[str, Any]]:
    if invoice_no is None:
        return []

    base_conditions = [
        "org_id = %(org_id)s",
        "vendor_id = %(vendor_id)s",
        "id <> %(invoice_id)s",
    ]
    values: Dict[str, Any] = {
        "org_id": org_id,
        "vendor_id": vendor_id,
        "invoice_id": invoice_id,
    }

    if invoice_no is None:
        return []

    values["invoice_no"] = invoice_no
    where_clause = " AND ".join(base_conditions)
    where_clause += " AND invoice_no = %(invoice_no)s"

    query = f"""
        SELECT
          id,
          vendor_id,
          invoice_no,
          total,
          invoice_date
        FROM invoices
        WHERE {where_clause};
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, values)
        return await cur.fetchall()


async def _score_vendor_volume_spikes_for_invoice(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[AlertCandidate]:
    """
    Rule: flag invoices whose total is significantly higher than the vendor's
    historical average invoice total.

    Severity bands:
      medium — 2x–3x baseline average
      high   — 3x+ baseline average
    """
    rows = await _fetch_invoice_lines(db, org_id=org_id, invoice_id=invoice_id)
    if not rows:
        return []

    header = rows[0]
    vendor_id = header["vendor_id"]
    invoice_no = header["invoice_no"]
    invoice_total = header["invoice_total"]

    if invoice_total is None:
        return []

    baseline = await get_single_vendor_spend_stats(
        db,
        org_id=org_id,
        vendor_id=vendor_id,
    )
    if baseline is None:
        return []

    count_90d = baseline["invoice_count_90d"] or 0
    count_30d = baseline["invoice_count_30d"] or 0
    median_90d = baseline["median_invoice_total_90d"]
    median_30d = baseline["median_invoice_total_30d"]

    baseline_window = None
    baseline_median_total: Optional[float] = None

    if count_90d >= MIN_INVOICES_FOR_SPEND_BASELINE and median_90d:
        baseline_window = "90d"
        baseline_median_total = float(median_90d)
    elif count_30d >= MIN_INVOICES_FOR_SPEND_BASELINE and median_30d:
        baseline_window = "30d"
        baseline_median_total = float(median_30d)

    if baseline_median_total is None or baseline_median_total <= 0:
        return []

    ratio = float(invoice_total) / float(baseline_median_total)

    severity: Optional[str] = None
    if ratio >= HIGH_TOTAL_RATIO_THRESHOLD:
        severity = "high"
    elif ratio >= MEDIUM_TOTAL_RATIO_THRESHOLD:
        severity = "medium"

    if severity is None:
        return []

    message = (
        f"Invoice total {invoice_total:.2f} on invoice "
        f"{invoice_no or invoice_id} is {ratio:.2f}x the vendor's "
        f"median invoice total over the last {baseline_window}."
    )

    meta: Dict[str, Any] = {
        "rule": "vendor_volume_spike",
        "ratio": ratio,
        "baseline_window": baseline_window,
        "baseline_median_total": baseline_median_total,
        "invoice_total": float(invoice_total),
        "invoice_no": invoice_no,
        "invoice_id": str(invoice_id),
        "vendor_id": str(vendor_id),
        "counts": {
            "invoice_count_30d": count_30d,
            "invoice_count_90d": count_90d,
        },
    }

    return [
        AlertCandidate(
            org_id=str(org_id),
            invoice_id=str(invoice_id),
            vendor_id=str(vendor_id),
            type="vendor_volume_spike",
            severity=severity,
            message=message,
            meta=meta,
        )
    ]


async def _score_duplicate_invoices_for_invoice(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[AlertCandidate]:
    """
    Rule: detect potential duplicate invoices for the same vendor.

    Severity:
      critical — duplicate matches both invoice_no AND total
      medium   — duplicate matches only invoice_no or only total
    """
    rows = await _fetch_invoice_lines(db, org_id=org_id, invoice_id=invoice_id)
    if not rows:
        return []

    header = rows[0]
    vendor_id = header["vendor_id"]
    invoice_no = header["invoice_no"]
    invoice_total = header["invoice_total"]

    duplicates = await _find_potential_duplicate_invoices(
        db,
        org_id=org_id,
        vendor_id=vendor_id,
        invoice_id=invoice_id,
        invoice_no=invoice_no,
    )
    if not duplicates:
        return []

    duplicate_summaries: List[Dict[str, Any]] = []
    any_strong_match = False

    for dup in duplicates:
        dup_id = dup["id"]
        dup_invoice_no = dup["invoice_no"]
        dup_total = dup["total"]
        dup_date = dup["invoice_date"]

        match_on_invoice_no = invoice_no is not None and dup_invoice_no == invoice_no
        match_on_total = invoice_total is not None and dup_total == invoice_total

        if match_on_invoice_no and match_on_total:
            any_strong_match = True

        duplicate_summaries.append(
            {
                "invoice_id": str(dup_id),
                "invoice_no": dup_invoice_no,
                "total": float(dup_total) if dup_total is not None else None,
                "invoice_date": str(dup_date) if dup_date is not None else None,
                "match_on": {
                    "invoice_no": match_on_invoice_no,
                    "total": match_on_total,
                },
            }
        )

    # critical if any duplicate matches both invoice_no and total (near-certain duplicate)
    severity = "critical" if any_strong_match else "medium"

    message = (
        f"Invoice {invoice_no or invoice_id} for vendor {vendor_id} "
        f"has {len(duplicate_summaries)} potential duplicate(s) "
        f"based on matching invoice number and/or total."
    )

    meta: Dict[str, Any] = {
        "rule": "duplicate_invoice",
        "candidate_invoice_id": str(invoice_id),
        "candidate_invoice_no": invoice_no,
        "candidate_invoice_total": float(invoice_total) if invoice_total is not None else None,
        "duplicates": duplicate_summaries,
    }

    return [
        AlertCandidate(
            org_id=str(org_id),
            invoice_id=str(invoice_id),
            vendor_id=str(vendor_id),
            type="duplicate_invoice",
            severity=severity,
            message=message,
            meta=meta,
        )
    ]


async def _score_contract_policy_violations_for_invoice(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[AlertCandidate]:
    """
    Rule: flag invoices that violate terms stored in vendor_contracts.

    Three sub-rules (each produces a separate alert if triggered):
      spending_limit_exceeded  — invoice total > contract spending limit       → high
      unapproved_category      — line item desc/sku not in approved_categories → high
      payment_terms_violation  — due_date - invoice_date > payment_terms_days  → medium
    """
    rows = await _fetch_invoice_lines(db, org_id=org_id, invoice_id=invoice_id)
    if not rows:
        return []

    header = rows[0]
    vendor_id = header["vendor_id"]
    invoice_no = header["invoice_no"]
    invoice_total = header["invoice_total"]
    invoice_date = header["invoice_date"]
    due_date = header["due_date"]

    contract = await get_vendor_contract(db, org_id=org_id, vendor_id=vendor_id)
    if contract is None:
        return []

    candidates: List[AlertCandidate] = []

    # 1. Spending limit
    spending_limit = contract["spending_limit"]
    if spending_limit is not None and invoice_total is not None:
        if float(invoice_total) > float(spending_limit):
            candidates.append(
                AlertCandidate(
                    org_id=str(org_id),
                    invoice_id=str(invoice_id),
                    vendor_id=str(vendor_id),
                    type="contract_policy_violation",
                    severity="high",
                    message=(
                        f"Invoice {invoice_no or invoice_id} total {float(invoice_total):.2f} "
                        f"exceeds the contract spending limit of {float(spending_limit):.2f} "
                        f"for this vendor."
                    ),
                    meta={
                        "rule": "spending_limit_exceeded",
                        "invoice_total": float(invoice_total),
                        "spending_limit": float(spending_limit),
                        "invoice_no": invoice_no,
                    },
                )
            )

    # 2. Approved categories — checked per line item
    approved_categories: Optional[List[str]] = contract["approved_categories"]
    if approved_categories:
        for row in rows:
            desc = (row["desc"] or "").lower()
            sku = (row["sku"] or "").lower()
            line_text = f"{desc} {sku}".strip()
            matches_any = any(cat.lower() in line_text for cat in approved_categories)
            if not matches_any:
                candidates.append(
                    AlertCandidate(
                        org_id=str(org_id),
                        invoice_id=str(invoice_id),
                        vendor_id=str(vendor_id),
                        type="contract_policy_violation",
                        severity="high",
                        message=(
                            f"Line item '{row['desc'] or row['sku']}' on invoice "
                            f"{invoice_no or invoice_id} does not match any approved "
                            f"spend category for this vendor contract."
                        ),
                        meta={
                            "rule": "unapproved_category",
                            "line_desc": row["desc"],
                            "line_sku": row["sku"],
                            "approved_categories": approved_categories,
                            "invoice_no": invoice_no,
                            "line_id": str(row["line_id"]),
                        },
                    )
                )

    # 3. Payment terms
    payment_terms_days = contract["payment_terms_days"]
    if payment_terms_days is not None and due_date is not None and invoice_date is not None:
        actual_days = (due_date - invoice_date).days
        if actual_days > payment_terms_days:
            candidates.append(
                AlertCandidate(
                    org_id=str(org_id),
                    invoice_id=str(invoice_id),
                    vendor_id=str(vendor_id),
                    type="contract_policy_violation",
                    severity="medium",
                    message=(
                        f"Invoice {invoice_no or invoice_id} requests payment in {actual_days} days, "
                        f"exceeding the contracted payment terms of {payment_terms_days} days."
                    ),
                    meta={
                        "rule": "payment_terms_violation",
                        "actual_days": actual_days,
                        "contracted_days": payment_terms_days,
                        "invoice_date": str(invoice_date),
                        "due_date": str(due_date),
                        "invoice_no": invoice_no,
                    },
                )
            )

    return candidates


# ── Excessive consulting thresholds ─────────────────────────────────────────
_CONSULTING_KEYWORDS = {
    "consulting",
    "advisory",
    "professional services",
    "professional fee",
    "management consulting",
}
_CONSULTING_TOTAL_MEDIUM_THRESHOLD = 5_000.0  # flag if total > $5k and no contract found
_DOLLAR_PATTERN = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
_PER_HOUR_PATTERN = re.compile(r"per\s+hour|/\s*hr\b|hourly", re.IGNORECASE)


def _is_consulting_line(desc: str) -> bool:
    desc_lower = desc.lower()
    return any(kw in desc_lower for kw in _CONSULTING_KEYWORDS)


def _extract_rates_from_text(text: str) -> list:
    """Return all hourly rates found in text.

    Handles both inline format ($185.00 per hour) and contract format where
    'per hour' appears in the service name on the same line as the price:
      - Software Engineering Consulting (per hour): $185.00 ± $15.00 per unit
    """
    rates = []
    for line in text.splitlines():
        if _PER_HOUR_PATTERN.search(line):
            m = _DOLLAR_PATTERN.search(line)
            if m:
                try:
                    rates.append(float(m.group(1).replace(",", "")))
                except ValueError:
                    pass
    return rates


async def _search_chunks_async(
    db: Any,
    org_id: str,
    query: str,
    source_types: Optional[List[str]] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Async wrapper: embeds the query and queries doc_chunks via the async DB."""
    import os
    try:
        from openai import OpenAI
        from apps.api.settings import settings
        api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
        if not api_key:
            return []
        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=[query],
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        vector = resp.data[0].embedding
        vector_str = "[" + ",".join(str(v) for v in vector) + "]"
    except Exception:
        return []

    query_sql = """
        SELECT
          id,
          source_type,
          source_name,
          chunk_text,
          meta_json,
          1 - (embedding <=> %(vec)s::vector) AS similarity
        FROM doc_chunks
        WHERE org_id = %(org_id)s
          AND (%(types)s::text[] IS NULL OR source_type = ANY(%(types)s::text[]))
        ORDER BY embedding <=> %(vec)s::vector
        LIMIT %(limit)s
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query_sql,
            {"vec": vector_str, "org_id": org_id, "types": source_types, "limit": limit},
        )
        return await cur.fetchall()


async def _score_excessive_consulting_for_invoice(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[AlertCandidate]:
    """
    Rule: flag invoices that appear to contain excessive consulting/professional
    services spend relative to contract or policy limits found via vector search.

    Severity:
      high   — contract rate limit found and invoice rate exceeds it
      medium — consulting total > threshold and no contract evidence found
    """
    rows = await _fetch_invoice_lines(db, org_id=org_id, invoice_id=invoice_id)
    if not rows:
        return []

    header = rows[0]
    vendor_id = header["vendor_id"]
    invoice_no = header["invoice_no"]

    consulting_lines = [
        r for r in rows
        if r["desc"] and _is_consulting_line(r["desc"])
    ]
    if not consulting_lines:
        return []

    consulting_total = sum(
        float(r["line_total"]) for r in consulting_lines if r["line_total"] is not None
    )
    invoice_rates = [
        float(r["unit_price"])
        for r in consulting_lines
        if r["unit_price"] is not None and float(r["unit_price"]) > 50
    ]
    max_invoice_rate = max(invoice_rates) if invoice_rates else None

    # Vector search for relevant contract/policy clauses
    query_text = " ".join(
        r["desc"] for r in consulting_lines if r["desc"]
    ) + " consulting rate limit professional services cap hourly rate"
    chunks = await _search_chunks_async(
        db, org_id, query_text, source_types=["contract", "policy"], limit=5
    )

    # Only trust chunks with similarity ≥ 0.75 to avoid spurious rate comparisons
    # from unrelated contracts that happened to rank in the top-k.
    high_sim_chunks = [
        c for c in chunks
        if c.get("similarity") is not None and float(c["similarity"]) >= 0.75
    ]

    # Extract the maximum allowed hourly rate across all high-similarity chunks.
    # Using max (not min) because contracts list multiple tiers (e.g. $150 analyst,
    # $350 senior partner) — we only flag when the invoice rate exceeds the highest
    # contracted tier, which is the clearest sign of an out-of-contract charge.
    contract_rate: Optional[float] = None
    for chunk in high_sim_chunks:
        for rate in _extract_rates_from_text(chunk.get("chunk_text", "")):
            if contract_rate is None or rate > contract_rate:
                contract_rate = rate

    vector_evidence = [
        {
            "source_type": c["source_type"],
            "source_name": c["source_name"],
            "snippet": c["chunk_text"][:300],
            "similarity": float(c["similarity"]) if c.get("similarity") is not None else None,
        }
        for c in chunks
    ]

    severity: Optional[str] = None
    reason = ""

    if contract_rate is not None and max_invoice_rate is not None:
        if max_invoice_rate > contract_rate * 1.10:  # 10% tolerance for rounding/minor variance
            severity = "high"
            reason = (
                f"Invoice hourly rate {max_invoice_rate:.2f} exceeds contract rate limit "
                f"{contract_rate:.2f} found in retrieved contract/policy evidence."
            )
    elif high_sim_chunks and contract_rate is None and consulting_total > _CONSULTING_TOTAL_MEDIUM_THRESHOLD:
        # Relevant contracts were found but none specified an hourly rate —
        # flag for manual review since we can't validate the charges.
        severity = "medium"
        reason = (
            f"Consulting total {consulting_total:.2f} exceeds the "
            f"{_CONSULTING_TOTAL_MEDIUM_THRESHOLD:.0f} review threshold. "
            "No explicit contract rate limit found in retrieved documents."
        )

    if severity is None:
        return []

    line_summaries = [
        {
            "desc": r["desc"],
            "qty": float(r["qty"]) if r["qty"] is not None else None,
            "unit_price": float(r["unit_price"]) if r["unit_price"] is not None else None,
            "line_total": float(r["line_total"]) if r["line_total"] is not None else None,
        }
        for r in consulting_lines
    ]

    message = (
        f"Invoice {invoice_no or invoice_id} from vendor {vendor_id} contains "
        f"consulting/professional services charges totalling {consulting_total:.2f}. "
        f"{reason}"
    )

    meta: Dict[str, Any] = {
        "rule": "excessive_consulting",
        "consulting_total": consulting_total,
        "consulting_lines": line_summaries,
        "vector_evidence": vector_evidence,
        "contract_rate_found": contract_rate,
        "invoice_rate": max_invoice_rate,
        "invoice_no": invoice_no,
        "invoice_id": str(invoice_id),
        "vendor_id": str(vendor_id),
    }

    return [
        AlertCandidate(
            org_id=str(org_id),
            invoice_id=str(invoice_id),
            vendor_id=str(vendor_id),
            type="excessive_consulting",
            severity=severity,
            message=message,
            meta=meta,
        )
    ]


async def score_invoice(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[AlertCandidate]:
    """
    High-level scoring entry point for a single invoice.
    Aggregates alerts from all rule-based checks.
    """
    alerts: List[AlertCandidate] = []

    alerts.extend(
        await _score_unit_price_deltas_for_invoice(
            db, org_id=org_id, invoice_id=invoice_id
        )
    )

    alerts.extend(
        await _score_vendor_volume_spikes_for_invoice(
            db, org_id=org_id, invoice_id=invoice_id
        )
    )

    alerts.extend(
        await _score_duplicate_invoices_for_invoice(
            db, org_id=org_id, invoice_id=invoice_id
        )
    )

    alerts.extend(
        await _score_contract_policy_violations_for_invoice(
            db, org_id=org_id, invoice_id=invoice_id
        )
    )

    alerts.extend(
        await _score_excessive_consulting_for_invoice(
            db, org_id=org_id, invoice_id=invoice_id
        )
    )

    return alerts
