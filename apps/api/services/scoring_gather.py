"""The gathering adapter: where scoring reads the database.

Scoring an invoice is two steps — gather, then decide. This module is the first
step. Once every rule consumes the snapshot it will be the only scoring code
holding a connection, and everything downstream of ``gather_invoice_snapshot``
will be arithmetic over plain data. That is true of ``unit_price_delta``,
``vendor_volume_spike`` and ``contract_policy``, which are functions of the
snapshot and issue no query of their own; only ``excessive_consulting`` still
reads the database itself, and it does so deliberately — see clause 1 below.

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
   lives in the scoring module as ``select_price_baseline``. The vendor's spend
   Baselines arrive the same way — every row the view returns, with
   ``select_spend_baseline`` picking between them.

Three of the four rules consume it today, and the queries they used to issue
are gone with them: the per-line Baseline query, the vendor spend stats read,
and the vendor contract read all happen once here instead.

The duplicated reads go with them. Scoring an invoice with ``n`` lines used to
cost ``6 + n`` queries — four copies of the joined header-and-lines read, one
Baseline query per line, the spend stats and the contract. It now costs six,
whatever ``n`` is: these five, plus the one joined read
``excessive_consulting`` still makes for itself. That last copy goes when the
consulting rule crosses the seam, and the joined read goes with it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from apps.api.models.invoice_snapshot import InvoiceSnapshot
from apps.api.repos.contracts import get_vendor_contract
from apps.api.repos.invoice_stats import (
    get_vendor_spend_stats,
    get_vendor_unit_price_stats_for_skus,
)
from apps.api.repos.invoices import get_invoice_header, get_invoice_lines


async def gather_invoice_snapshot(
    db: Any,
    *,
    org_id: str,
    invoice_id: str,
) -> Optional[InvoiceSnapshot]:
    """Read one invoice and everything the rules will need to score it.

    Five reads: the header, the lines, one batched Baseline fetch for the
    Purchased Items those lines name, the vendor's spend Baselines, and the
    vendor's contract. All five are keyed by the invoice and its vendor, so
    none of them needs a scoring decision made first.

    Returns ``None`` when the invoice does not exist in this org. An invoice
    that exists but has no lines yields a snapshot with an empty ``lines`` —
    representable on purpose, because "an invoice with no lines raises no
    alerts" is a rule's conclusion to draw, not a gap in the data.
    """
    invoice = await get_invoice_header(db, org_id=org_id, invoice_id=invoice_id)
    if invoice is None:
        return None

    lines: List[Dict[str, Any]] = await get_invoice_lines(db, invoice_id=invoice_id)

    vendor_id = str(invoice["vendor_id"])

    price_baselines = await _gather_price_baselines(
        db,
        org_id=org_id,
        vendor_id=vendor_id,
        lines=lines,
    )

    spend_baselines = await get_vendor_spend_stats(
        db, org_id=org_id, vendor_id=vendor_id
    )

    contract = await get_vendor_contract(db, org_id=org_id, vendor_id=vendor_id)

    return InvoiceSnapshot(
        org_id=str(org_id),
        invoice=invoice,
        lines=lines,
        price_baselines=price_baselines,
        spend_baselines=spend_baselines,
        contract=contract,
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
