from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
    severity: str
    message: str
    meta: Dict[str, Any]


# Thresholds for rule-based scoring.
# These can be made org-configurable later if needed.
MIN_SAMPLE_SIZE_FOR_BASELINE = 5
HIGH_PRICE_RATIO_THRESHOLD = 3.0  # e.g., > 3x median price is "high" anomaly
MEDIUM_PRICE_RATIO_THRESHOLD = 2.0  # e.g., > 2x median price is "medium" anomaly

# Vendor-level volume spike thresholds.
MIN_INVOICES_FOR_SPEND_BASELINE = 3
HIGH_TOTAL_RATIO_THRESHOLD = 3.0  # e.g., > 3x avg invoice total is "high" anomaly
MEDIUM_TOTAL_RATIO_THRESHOLD = 2.0  # e.g., > 2x avg invoice total is "medium" anomaly


async def _fetch_invoice_lines(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[Dict[str, Any]]:
    """
    Load invoice header + line items for a given (org, invoice_id).

    This helper deliberately inlines a small query instead of depending on
    multiple repos to keep scoring logic cohesive.
    """
    query = """
        SELECT
          i.id AS invoice_id,
          i.org_id,
          i.vendor_id,
          i.invoice_no,
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
        WHERE i.org_id = :org_id
          AND i.id = :invoice_id;
    """
    return await db.fetch_all(
        query=query,
        values={"org_id": org_id, "invoice_id": invoice_id},
    )


async def _score_unit_price_deltas_for_invoice(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[AlertCandidate]:
    """
    Rule: flag line items whose unit price is significantly higher than the
    historical median price for the same (org, vendor, sku[, desc]).

    This uses the `vendor_unit_price_stats` view via
    `get_vendor_sku_baseline_price` to obtain a baseline median price and
    sample size.
    """
    # NOTE ABOUT LIMITATIONS:
    #
    # This rule assumes stable SKU/description data and consistent units of
    # measure. Real-world invoice data is noisy:
    #   - SKUs or descriptions may vary across invoices, reducing match quality.
    #   - Vendors may change pricing legitimately (inflation, contract changes).
    #   - Bulk purchases often have different unit pricing.
    #   - Packaging or unit-of-measure differences can distort unit_price.
    #
    # Therefore, this rule should be interpreted as: "flag unusually high unit
    # prices compared to past patterns," not "this line item is definitely wrong."
    rows = await _fetch_invoice_lines(db, org_id=org_id, invoice_id=invoice_id)
    if not rows:
        return []

    candidates: List[AlertCandidate] = []

    # All rows share the same header fields for a given invoice.
    header = rows[0]
    vendor_id = header["vendor_id"]
    invoice_no = header["invoice_no"]

    for row in rows:
        line_id = row["line_id"]
        sku = row["sku"]
        desc = row["desc"]
        unit_price = row["unit_price"]

        # Skip lines that don't have a meaningful price or SKU.
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
            # No historical data for this (org, vendor, sku[, desc]) yet;
            # we can't do a "price vs median" comparison.
            continue

        sample_size = (baseline["sample_size"] or 0)
        if sample_size < MIN_SAMPLE_SIZE_FOR_BASELINE:
            # Not enough history to trust the baseline.
            continue
        median_price: Optional[float] = baseline["median_unit_price"]
        if not median_price or median_price <= 0:
            # Guard against division by zero / bogus data.
            continue

        ratio = float(unit_price) / float(median_price)

        severity: Optional[str] = None
        if ratio >= HIGH_PRICE_RATIO_THRESHOLD:
            severity = "high"
        elif ratio >= MEDIUM_PRICE_RATIO_THRESHOLD:
            severity = "medium"

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
    invoice_total: Optional[float],
) -> List[Dict[str, Any]]:
    """
    Look for other invoices for the same vendor that may be duplicates of the
    given invoice. A potential duplicate is defined as another invoice with:
      - the same (org_id, vendor_id), and
      - a different id(it has to be different row so we don't match the invoice against itself), and
      - matching invoice_no and/or matching total.
    """
    # If we have neither an invoice number nor a total, we can't meaningfully
    # search for duplicates.
    if invoice_no is None and invoice_total is None:
        return []

    base_conditions = [
        "org_id = :org_id",
        "vendor_id = :vendor_id",
        "id <> :invoice_id",
    ]
    values: Dict[str, Any] = {
        "org_id": org_id,
        "vendor_id": vendor_id,
        "invoice_id": invoice_id,
    }

    match_clauses: List[str] = []
    if invoice_no is not None:
        match_clauses.append("invoice_no = :invoice_no")
        values["invoice_no"] = invoice_no
    if invoice_total is not None:
        match_clauses.append("total = :invoice_total")
        values["invoice_total"] = invoice_total

    where_clause = " AND ".join(base_conditions)
    where_clause += " AND (" + " OR ".join(match_clauses) + ")"

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
    return await db.fetch_all(query=query, values=values)

# Vendor-level volume spike rule
async def _score_vendor_volume_spikes_for_invoice(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[AlertCandidate]:
    """
    Rule: flag invoices whose total is significantly higher than the vendor's
    historical average invoice total over recent windows (e.g., 30–90 days).

    This uses the `vendor_spend_stats` view via
    `get_single_vendor_spend_stats` to obtain total spend and invoice counts.
    """
    # NOTE ABOUT LIMITATIONS:
    #
    # This rule is a *coarse heuristic* that compares the invoice total against
    # the vendor's average invoice total over a recent time window (30–90 days).
    #
    # It will correctly surface situations where:
    #   - a vendor suddenly bills far more than usual,
    #   - an unusually large one-off purchase appears,
    #   - a major billing mistake occurs (extra zeros, wrong quantity, etc.).
    #
    # BUT it can also raise *false positives* in completely legitimate cases:
    #   - rare capital purchases (e.g., buying a machine every 5 years),
    #   - seasonal or project-based spend spikes,
    #   - annual or quarterly renewals,
    #   - one-time bulk orders.
    #
    # In those scenarios, the spike is not an error — it's simply atypical
    # compared to the short-term history. This rule is about *surfacing unusual
    # behavior*, not deciding correctness. Later versions of the scoring engine
    # can reduce noise by using category-aware baselines, SKU clustering,
    # median-based comparisons, or ML-driven anomaly detection.
    rows = await _fetch_invoice_lines(db, org_id=org_id, invoice_id=invoice_id)
    if not rows:
        return []

    header = rows[0]
    vendor_id = header["vendor_id"]
    invoice_no = header["invoice_no"]
    invoice_total = header["invoice_total"]

    # If we don't have an invoice total, we can't apply this rule.
    if invoice_total is None:
        return []

    baseline = await get_single_vendor_spend_stats(
        db,
        org_id=org_id,
        vendor_id=vendor_id,
    )
    if baseline is None:
        # No historical invoices for this vendor yet.
        return []

    count_90d = baseline["invoice_count_90d"] or 0
    spend_90d = baseline["total_spend_90d"] or 0.0
    count_30d = baseline["invoice_count_30d"] or 0
    spend_30d = baseline["total_spend_30d"] or 0.0

    # Prefer the 90-day window if it has enough history; otherwise fall back to 30-day.
    baseline_window = None
    baseline_avg_total: Optional[float] = None

    if count_90d >= MIN_INVOICES_FOR_SPEND_BASELINE and spend_90d > 0:
        baseline_window = "90d"
        baseline_avg_total = float(spend_90d) / float(count_90d)
    elif count_30d >= MIN_INVOICES_FOR_SPEND_BASELINE and spend_30d > 0:
        baseline_window = "30d"
        baseline_avg_total = float(spend_30d) / float(count_30d)

    if baseline_avg_total is None or baseline_avg_total <= 0:
        # Not enough history to compute a meaningful average invoice total.
        return []

    ratio = float(invoice_total) / float(baseline_avg_total)

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
        f"average invoice total over the last {baseline_window}."
    )

    meta: Dict[str, Any] = {
        "rule": "vendor_volume_spike",
        "ratio": ratio,
        "baseline_window": baseline_window,
        "baseline_avg_total": baseline_avg_total,
        "invoice_total": float(invoice_total),
        "invoice_no": invoice_no,
        "invoice_id": str(invoice_id),
        "vendor_id": str(vendor_id),
        "counts": {
            "invoice_count_30d": count_30d,
            "invoice_count_90d": count_90d,
        },
        "spend": {
            "total_spend_30d": float(spend_30d),
            "total_spend_90d": float(spend_90d),
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

    For v1, we define a "potential duplicate" as another invoice with the same
    (org_id, vendor_id) and either:
      - the same invoice_no, or
      - the same total, or both.

    This is intentionally conservative and may surface legitimate repeats
    (e.g., monthly subscriptions with identical totals). It is meant to flag
    invoices for human review, not to automatically reject them.
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
        invoice_total=invoice_total,
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
                "invoice_date": dup_date,
                "match_on": {
                    "invoice_no": match_on_invoice_no,
                    "total": match_on_total,
                },
            }
        )

    # Simple severity heuristic:
    # - "high" if any duplicate matches both invoice_no and total.
    # - otherwise "medium" for duplicates that match on either field.
    severity = "high" if any_strong_match else "medium"

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


async def score_invoice(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> List[AlertCandidate]:
    """
    High-level scoring entry point for a single invoice.
    This function aggregates alerts from multiple rule-based checks.

    For v1, we implement:
      - unit price deltas vs vendor median (per SKU)
      - vendor-level volume spikes (invoice total vs historical averages)
      - potential duplicate invoices (same vendor + invoice_no and/or total)

    In the future, we can extend this to include:
      - other vendor- or category-level heuristics
    """
    alerts: List[AlertCandidate] = []

    # Unit price delta rule
    alerts.extend(
        await _score_unit_price_deltas_for_invoice(
            db,
            org_id=org_id,
            invoice_id=invoice_id,
        )
    )

    # Vendor-level volume spike rule
    alerts.extend(
        await _score_vendor_volume_spikes_for_invoice(
            db,
            org_id=org_id,
            invoice_id=invoice_id,
        )
    )

    # Duplicate-invoice rule
    alerts.extend(
        await _score_duplicate_invoices_for_invoice(
            db,
            org_id=org_id,
            invoice_id=invoice_id,
        )
    )

    # Future rules can be added here and their AlertCandidates appended
    # to the list.

    return alerts