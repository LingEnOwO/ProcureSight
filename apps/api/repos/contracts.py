from typing import Any, Dict, Optional

from psycopg.rows import dict_row


async def get_vendor_contract(
    db: Any,
    *,
    org_id: str,
    vendor_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Return the active contract for (org_id, vendor_id), or None if no contract
    exists or none is currently in effect.

    A contract is considered active when:
      - effective_date is NULL or <= today
      - expiry_date is NULL or >= today
    """
    query = """
        SELECT
            id,
            spending_limit,
            approved_categories,
            payment_terms_days,
            effective_date,
            expiry_date
        FROM vendor_contracts
        WHERE org_id = %(org_id)s
          AND vendor_id = %(vendor_id)s
          AND (effective_date IS NULL OR effective_date <= current_date)
          AND (expiry_date IS NULL OR expiry_date >= current_date)
        LIMIT 1;
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"org_id": org_id, "vendor_id": vendor_id})
        return await cur.fetchone()
