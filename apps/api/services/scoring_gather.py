"""The gathering adapter: where scoring will read the database.

Scoring an invoice is two steps — gather, then decide. This module is the first
step. Once the rules consume the snapshot it will be the only scoring code
holding a connection, and everything downstream of ``gather_invoice_snapshot``
will be arithmetic over plain data. That is not true yet: the rules in
``anomaly_scoring`` still read the database themselves, and will until the next
change moves them over.

The adapter obeys two clauses, and they decide every case that comes after:

1. **Prefetch data whose keys are derivable from the snapshot input without
   making a scoring decision.** The Baseline keys are the SKUs on the invoice's
   lines — a projection of the lines, not a judgement about them, so they
   qualify. Contrast the consulting rule's document retrieval, whose key
   requires classifying which lines *are* consulting: that is rule-owned and
   stays behind an injected port rather than moving here.
2. **Return everything matching those keys, and never narrow.** No "best" row,
   no threshold, no drop. Where the code this replaces relied on ``ORDER BY
   sample_size DESC`` plus taking the first row, that selection is a rule and
   lives in the scoring module as ``select_price_baseline``.

Nothing consumes the snapshot yet — the rules still read the database
themselves. Making it load-bearing is the next change.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from apps.api.models.invoice_snapshot import InvoiceSnapshot
from apps.api.repos.invoice_stats import get_vendor_unit_price_stats_for_skus
from apps.api.repos.invoices import get_invoice_header, get_invoice_lines


async def gather_invoice_snapshot(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> Optional[InvoiceSnapshot]:
    """Read one invoice and everything the rules will need to score it.

    Three reads: the header, the lines, and one batched Baseline fetch for the
    Purchased Items those lines name.

    Returns ``None`` when the invoice does not exist in this org. An invoice
    that exists but has no lines yields a snapshot with an empty ``lines`` —
    representable on purpose, because "an invoice with no lines raises no
    alerts" is a rule's conclusion to draw, not a gap in the data.
    """
    invoice = await get_invoice_header(db, org_id=org_id, invoice_id=invoice_id)
    if invoice is None:
        return None

    lines: List[Dict[str, Any]] = await get_invoice_lines(db, invoice_id=invoice_id)

    price_baselines = await _gather_price_baselines(
        db,
        org_id=org_id,
        vendor_id=str(invoice["vendor_id"]),
        lines=lines,
    )

    return InvoiceSnapshot(
        org_id=str(org_id),
        invoice=invoice,
        lines=lines,
        price_baselines=price_baselines,
    )


async def _gather_price_baselines(
    db: Any,
    *,
    org_id: str,
    vendor_id: str,
    lines: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Baselines for the Purchased Items on these lines, in one round trip.

    The keys are the distinct SKUs on the lines. A line with no SKU names no
    Purchased Item (ADR-0001) and so contributes no key. A SKU with no history
    contributes no entry to the result.
    """
    skus = sorted({line["sku"] for line in lines if line["sku"] is not None})
    rows = await get_vendor_unit_price_stats_for_skus(
        db, org_id=org_id, vendor_id=vendor_id, skus=skus
    )

    by_sku: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_sku.setdefault(row["sku"], []).append(row)
    return by_sku
