from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import psycopg
from psycopg.rows import dict_row


# NOTE:
# - These helpers are intentionally lightweight and do not assume a specific DB
#   library (asyncpg, databases, SQLAlchemy, etc).
# - The only expectation is that `db` exposes `fetch_one` / `fetch_all`-style
#   coroutine methods that accept a SQL string plus `values`/`parameters`,
#   which matches how the other repos in this app are structured.
#
# Example usage (with `databases.Database`):
#
#   from apps.api.db import database
#   stats = await get_vendor_unit_price_stats(
#       db=database,
#       org_id=org_id,
#       vendor_id=vendor_id,
#       sku="ABC-123",
#   )
#
# These helpers sit on top of the `vendor_unit_price_stats` view defined in
# `scripts/seed.py` and are used by anomaly scoring logic to look up
# historical price baselines for a given org/vendor/SKU/description.


async def get_vendor_unit_price_stats(
    db: Any,
    *,
    org_id: str,
    vendor_id: Optional[str] = None,
    sku: Optional[str] = None,
    desc: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch per-vendor unit price statistics from the `vendor_unit_price_stats` view.

    Parameters
    ----------
    db:
        Database/connection object with an `fetch_all(query, values)` coroutine.
    org_id:
        The organization ID to scope the query.
    vendor_id:
        Optional vendor ID to filter by. If omitted, returns stats for all vendors
        in the org.
    sku:
        Optional SKU filter.
    desc:
        Optional description filter. Note that this is matched exactly against the
        `desc` column in the view; if you want fuzzy matching, do that in a higher
        layer.

    Returns
    -------
    List[Dict[str, Any]]
        Zero or more rows from `vendor_unit_price_stats`, each with keys:
        `org_id`, `vendor_id`, `sku`, `desc`, `sample_size`,
        `median_unit_price`, and `mean_unit_price`.
    """
    conditions = ["org_id = %(org_id)s"]
    values: Dict[str, Any] = {"org_id": org_id}

    if vendor_id is not None:
        conditions.append("vendor_id = %(vendor_id)s")
        values["vendor_id"] = vendor_id

    if sku is not None:
        conditions.append("sku = %(sku)s")
        values["sku"] = sku

    if desc is not None:
        # `desc` is a reserved word; the view uses `\"desc\"` as the column name.
        conditions.append('"desc" = %(desc)s')
        values["desc"] = desc

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
          org_id,
          vendor_id,
          sku,
          "desc",
          sample_size,
          median_unit_price,
          mean_unit_price
        FROM vendor_unit_price_stats
        WHERE {where_clause}
        ORDER BY sample_size DESC, "desc";
    """

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, values)
        return await cur.fetchall()


async def get_vendor_sku_baseline_price(
    db: Any,
    *,
    org_id: str,
    vendor_id: str,
    sku: str,
    desc: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Convenience helper: fetch a single baseline price record for a given
    (org, vendor, sku[, desc]).

    If multiple rows exist (e.g., duplicate SKU/description variants), the row
    with the largest `sample_size` will be returned.

    Returns
    -------
    Dict[str, Any] | None
        A single stats row from `vendor_unit_price_stats`, or None if no stats
        exist for the given key.
    """
    rows = await get_vendor_unit_price_stats(
        db,
        org_id=org_id,
        vendor_id=vendor_id,
        sku=sku,
        desc=desc,
    )
    if not rows:
        return None

    # Because `get_vendor_unit_price_stats` already orders by sample_size DESC,
    # the first row is the best baseline candidate.
    return rows[0]


async def get_vendor_unit_price_stats_for_skus(
    db: Any,
    *,
    org_id: str,
    vendor_id: str,
    skus: Sequence[str],
) -> List[Dict[str, Any]]:
    """
    Fetch unit price statistics for a *set* of the vendor's SKUs in one round trip.

    This is the batched form of `get_vendor_unit_price_stats`, for the case the
    scoring adapter has: an invoice's worth of SKUs, wanted together. Scoring an
    invoice used to issue one query per line; this issues one per invoice.

    It fetches only the SKUs asked for — never the vendor's whole baseline set —
    so the result size follows the invoice rather than the vendor's history.

    No narrowing happens here. Every row matching a requested SKU comes back,
    including the several description variants the view still groups separately
    (see ADR-0001). Choosing between them is a scoring rule; see
    `apps.api.services.anomaly_scoring.select_price_baseline`.

    Rows are ordered by `sample_size DESC`, then `"desc"`, within a SKU —
    the same relative order `get_vendor_unit_price_stats` returns for a single
    SKU. The description is a tiebreaker, not a preference: the view groups by
    `(org, vendor, sku, "desc")`, so it makes the order total, and without it two
    baselines tied on `sample_size` could come back in either order and the
    caller's "first row" would vary between the two queries.

    Parameters
    ----------
    skus:
        The SKUs to fetch baselines for. An empty sequence issues no query and
        returns no rows.

    Returns
    -------
    List[Dict[str, Any]]
        Rows from `vendor_unit_price_stats` with the same keys the singular
        helpers return: `org_id`, `vendor_id`, `sku`, `"desc"`, `sample_size`,
        `median_unit_price`, `mean_unit_price`.
    """
    sku_list = list(skus)
    if not sku_list:
        return []

    query = """
        SELECT
          org_id,
          vendor_id,
          sku,
          "desc",
          sample_size,
          median_unit_price,
          mean_unit_price
        FROM vendor_unit_price_stats
        WHERE org_id = %(org_id)s
          AND vendor_id = %(vendor_id)s
          AND sku = ANY(%(skus)s)
        ORDER BY sku, sample_size DESC, "desc";
    """

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {"org_id": org_id, "vendor_id": vendor_id, "skus": sku_list},
        )
        return await cur.fetchall()


# --- Vendor spend stats helpers ---

async def get_vendor_spend_stats(
    db: Any,
    *,
    org_id: str,
    vendor_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch per-vendor spend and invoice-count statistics from the
    `vendor_spend_stats` view.

    Parameters
    ----------
    db:
        Database/connection object with a `fetch_all(query, values)` coroutine.
    org_id:
        The organization ID to scope the query.
    vendor_id:
        Optional vendor ID to filter by. If omitted, returns stats for all
        vendors in the org.

    Returns
    -------
    List[Dict[str, Any]]
        Zero or more rows from `vendor_spend_stats`, each with keys:
        `org_id`, `vendor_id`, `invoice_count_30d`, `total_spend_30d`,
        `median_invoice_total_30d`, `invoice_count_90d`, `total_spend_90d`,
        and `median_invoice_total_90d`.
    """
    conditions = ["org_id = %(org_id)s"]
    values: Dict[str, Any] = {"org_id": org_id}

    if vendor_id is not None:
        conditions.append("vendor_id = %(vendor_id)s")
        values["vendor_id"] = vendor_id

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
          org_id,
          vendor_id,
          invoice_count_30d,
          total_spend_30d,
          median_invoice_total_30d,
          invoice_count_90d,
          total_spend_90d,
          median_invoice_total_90d
        FROM vendor_spend_stats
        WHERE {where_clause}
        ORDER BY total_spend_90d DESC;
    """

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, values)
        return await cur.fetchall()


async def get_single_vendor_spend_stats(
    db: Any,
    *,
    org_id: str,
    vendor_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Convenience helper: fetch a single vendor's spend stats record from
    `vendor_spend_stats` for a given (org_id, vendor_id).

    Returns
    -------
    Dict[str, Any] | None
        A single stats row, or None if no stats exist for the given key.
    """
    rows = await get_vendor_spend_stats(
        db,
        org_id=org_id,
        vendor_id=vendor_id,
    )
    if not rows:
        return None

    # The view groups by (org_id, vendor_id), so there should be at most one row.
    return rows[0]