from __future__ import annotations

from typing import Any, Dict, List, Optional


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
    conditions = ["org_id = :org_id"]
    values: Dict[str, Any] = {"org_id": org_id}

    if vendor_id is not None:
        conditions.append("vendor_id = :vendor_id")
        values["vendor_id"] = vendor_id

    if sku is not None:
        conditions.append("sku = :sku")
        values["sku"] = sku

    if desc is not None:
        # `desc` is a reserved word; the view uses `\"desc\"` as the column name.
        conditions.append('"desc" = :desc')
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
        ORDER BY sample_size DESC;
    """

    return await db.fetch_all(query=query, values=values)


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
        `invoice_count_90d`, and `total_spend_90d`.
    """
    conditions = ["org_id = :org_id"]
    values: Dict[str, Any] = {"org_id": org_id}

    if vendor_id is not None:
        conditions.append("vendor_id = :vendor_id")
        values["vendor_id"] = vendor_id

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
          org_id,
          vendor_id,
          invoice_count_30d,
          total_spend_30d,
          invoice_count_90d,
          total_spend_90d
        FROM vendor_spend_stats
        WHERE {where_clause}
        ORDER BY total_spend_90d DESC;
    """

    return await db.fetch_all(query=query, values=values)


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