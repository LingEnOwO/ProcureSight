from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from psycopg.rows import dict_row

from apps.api.models.alert import AlertCandidate
from apps.api.models.invoice_snapshot import InvoiceSnapshot
from apps.api.repos.contracts import get_vendor_contract
from apps.api.repos.invoice_stats import get_single_vendor_spend_stats
from apps.api.services.scoring_gather import gather_invoice_snapshot

logger = logging.getLogger(__name__)


# ── Unit price delta thresholds ──────────────────────────────────────────────
MIN_SAMPLE_SIZE_FOR_BASELINE = 5
LOW_PRICE_RATIO_THRESHOLD = 1.5     # 1.5x–2x  → "low"
MEDIUM_PRICE_RATIO_THRESHOLD = 2.0  # 2x–3x    → "medium"
HIGH_PRICE_RATIO_THRESHOLD = 3.0    # 3x+       → "high"

# ── Vendor volume spike thresholds ───────────────────────────────────────────
MIN_INVOICES_FOR_SPEND_BASELINE = 5
MEDIUM_TOTAL_RATIO_THRESHOLD = 2.0  # 2x–3x    → "medium"
HIGH_TOTAL_RATIO_THRESHOLD = 3.0    # 3x+       → "high"


def select_price_baseline(
    baselines: List[Dict[str, Any]],
    *,
    desc: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Pick the one Baseline a line is compared against, out of the SKU's rows.

    This is a rule, not I/O, which is why it lives here: it decides which slice
    of a Purchased Item's history counts as "the" baseline. The gathering
    adapter hands over every row for the SKU and makes no such choice.

    It reproduces exactly what the per-line query it replaces resolved to:

    * a line with a description compares against the rows recorded under that
      same description, taking the best-sampled of them;
    * a line with no description compares against the SKU's best-sampled row,
      whatever description it was recorded under.

    That description matching is the behaviour ADR-0001 says is wrong — Line
    Description carries no identity — but the `vendor_unit_price_stats` view
    still groups by it, and realigning the two is a separate, behaviour-changing
    change. Keeping the mismatch in one named function is what makes it a single
    line to delete when that change lands.

    Parameters
    ----------
    baselines:
        The rows for one SKU, as the snapshot holds them: ordered by
        `sample_size` descending, un-narrowed.
    desc:
        The line's description, or None.

    Returns
    -------
    Dict[str, Any] | None
        The chosen Baseline row, or None if nothing matches.
    """
    candidates = baselines if desc is None else [b for b in baselines if b["desc"] == desc]
    return candidates[0] if candidates else None


async def _fetch_invoice_lines(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[Dict[str, Any]]:
    """One invoice joined to its lines, one flat row per line, scoped to an org.

    The pre-seam read: the three rules that still hold a connection take their
    header fields off the first row and iterate the rest. ``unit_price_delta``
    does not call it — it reads the same data off the snapshot — and the last
    caller goes away when the remaining rules cross the seam, at which point
    this goes with them.
    """
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


def score_unit_price_deltas(snapshot: InvoiceSnapshot) -> List[AlertCandidate]:
    """
    Rule: flag line items whose unit price is significantly higher than the
    historical median price for the same (org, vendor, sku[, desc]).

    Severity bands:
      low    — 1.5x–2x median
      medium — 2x–3x median
      high   — 3x+ median

    A function of the snapshot, not of a connection. Every Baseline it needs is
    already in ``snapshot.price_baselines``, keyed by SKU and un-narrowed;
    choosing which of a SKU's rows a line is compared against is
    ``select_price_baseline``, above.
    """
    invoice = snapshot.invoice
    invoice_id = str(invoice["id"])
    vendor_id = invoice["vendor_id"]
    invoice_no = invoice["invoice_no"]

    candidates: List[AlertCandidate] = []

    for line in snapshot.lines:
        line_id = line["id"]
        sku = line["sku"]
        desc = line["desc"]
        unit_price = line["unit_price"]

        if unit_price is None or sku is None:
            continue

        baseline = select_price_baseline(snapshot.price_baselines.get(sku, []), desc=desc)
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
            "invoice_id": invoice_id,
            "vendor_id": str(vendor_id),
            "line_id": str(line_id),
        }

        candidates.append(
            AlertCandidate(
                org_id=snapshot.org_id,
                invoice_id=invoice_id,
                vendor_id=str(vendor_id),
                type="unit_price_delta",
                severity=severity,
                message=message,
                meta=meta,
            )
        )

    return candidates


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


def build_duplicate_alert(
    *,
    org_id: str,
    vendor_id: str,
    existing: Dict[str, Any],
    incoming_invoice_no: str,
    incoming_vendor: str,
    incoming_total: float,
    incoming_raw_doc_id: int,
) -> AlertCandidate:
    """Build the alert for a re-submitted invoice that duplicates an existing one.

    Duplicates are caught in the worker *before* insert (via
    ``find_invoice_by_key``), so the duplicate row is never written and there is
    nothing to "score" post-hoc. This function owns the alert's shape and
    severity so that — like every other alert type — that decision lives in the
    scoring domain rather than in the worker's orchestration code.

    Severity:
      critical — the existing invoice's total also matches (near-certain duplicate)
      high     — same vendor + invoice_no but a different total (possibly a
                 corrected re-upload; still worth a human look)
    """
    existing_invoice_id = str(existing["id"])
    matched = ["vendor_id", "invoice_no"]
    existing_total = existing.get("total")
    if existing_total is not None and float(existing_total) == float(incoming_total):
        matched.append("total")
    severity = "critical" if "total" in matched else "high"

    return AlertCandidate(
        org_id=str(org_id),
        invoice_id=existing_invoice_id,
        vendor_id=str(vendor_id),
        type="duplicate_invoice",
        severity=severity,
        message=(
            f"Invoice {incoming_invoice_no} from {incoming_vendor} was re-submitted — "
            f"matches existing invoice on {', '.join(matched)}."
        ),
        meta={
            "rule": "duplicate_invoice_no_same_vendor",
            "existing_invoice_id": existing_invoice_id,
            "incoming_raw_doc_id": incoming_raw_doc_id,
            "incoming_invoice_no": incoming_invoice_no,
            "incoming_total": float(incoming_total),
            "matched_fields": matched,
        },
    )


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


_MIN_SIMILARITY = 0.5


async def _search_chunks_async(
    db: Any,
    org_id: str,
    query: str,
    source_types: Optional[List[str]] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Embed query async and return the top matching doc_chunks above a similarity floor."""
    from openai import AsyncOpenAI
    from apps.api.settings import settings

    api_key = settings.openai_api_key
    if not api_key:
        return []

    try:
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=[query],
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
        vector_str = "[" + ",".join(str(v) for v in resp.data[0].embedding) + "]"
    except Exception as e:
        logger.warning("_search_chunks_async: embedding query failed: %s", e)
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
          AND embedding IS NOT NULL
          AND (%(types)s::text[] IS NULL OR source_type = ANY(%(types)s::text[]))
          AND 1 - (embedding <=> %(vec)s::vector) >= %(min_sim)s
        ORDER BY embedding <=> %(vec)s::vector
        LIMIT %(limit)s
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query_sql,
            {
                "vec": vector_str,
                "org_id": org_id,
                "types": source_types,
                "limit": limit,
                "min_sim": _MIN_SIMILARITY,
            },
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

    logger.info(
        "excessive_consulting vector search | invoice=%s | chunks_returned=%d",
        invoice_no or invoice_id,
        len(chunks),
    )
    for i, c in enumerate(chunks):
        logger.debug(
            "  chunk[%d] source=%s | similarity=%.3f | text=%r",
            i,
            c.get("source_name"),
            c.get("similarity") or 0.0,
            c.get("chunk_text", "")[:200],
        )

    # Extract the maximum allowed hourly rate from the top-ranked chunk only.
    # Using the top-1 chunk avoids polluting the rate comparison with lower-ranked
    # chunks from unrelated contracts. Using max (not min) across tiers within that
    # chunk means we only flag when the invoice rate exceeds the highest contracted
    # tier — the clearest sign of an out-of-contract charge.
    contract_rate: Optional[float] = None
    if chunks:
        for rate in _extract_rates_from_text(chunks[0].get("chunk_text", "")):
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
    elif not chunks and consulting_total > _CONSULTING_TOTAL_MEDIUM_THRESHOLD:
        # No contract or policy evidence found at all — flag for manual review
        # since we cannot validate whether these charges are authorised.
        severity = "medium"
        reason = (
            f"Consulting total {consulting_total:.2f} exceeds the "
            f"{_CONSULTING_TOTAL_MEDIUM_THRESHOLD:.0f} review threshold and no "
            "contract or policy evidence was found for this vendor."
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

    Half gather-then-decide, half not, and that is the state of the migration
    rather than a design: ``unit_price_delta`` is a function of the snapshot,
    while the other three still take the connection and read what they need.
    """
    alerts: List[AlertCandidate] = []

    # A missing invoice yields no snapshot and so no alerts — the same silence
    # the connection-taking rules produce when their query comes back empty.
    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=invoice_id)
    if snapshot is not None:
        alerts.extend(score_unit_price_deltas(snapshot))

    alerts.extend(
        await _score_vendor_volume_spikes_for_invoice(
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
