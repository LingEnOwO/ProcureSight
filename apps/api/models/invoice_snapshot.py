from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class InvoiceSnapshot:
    """Everything the scoring rules need about one invoice, as plain data.

    Built by the gathering adapter (``apps.api.services.scoring_gather``) and
    consumed by rules that hold no connection. It lives in the models package
    rather than beside either of them because it is the seam itself: the
    adapter's output type and the rules' input type.

    The two clauses the adapter obeys are visible in the shape:

    * every field's key is derivable from the invoice without making a scoring
      decision — ``price_baselines`` is keyed by the SKUs on the lines, which is
      a projection of the lines rather than a judgement about them;
    * nothing here is narrowed. ``price_baselines`` maps a SKU to *every*
      Baseline row matching it, in the order the view returned them. Picking one
      is a rule (see ``select_price_baseline``), not I/O.

    Attributes
    ----------
    org_id:
        The tenant this snapshot was gathered under.
    invoice:
        The invoice header row: ``id``, ``vendor_id``, ``invoice_no``,
        ``invoice_date``, ``due_date``, ``total``.
    lines:
        The invoice's lines: ``id``, ``sku``, ``desc``, ``qty``, ``unit_price``,
        ``line_total``. May be empty — an invoice with no lines is representable,
        and what that means for alerts is a rule's decision.
    price_baselines:
        SKU → the Baseline rows for that Purchased Item, from
        ``vendor_unit_price_stats``. Only SKUs present on ``lines`` appear, so
        snapshot size follows the invoice rather than the vendor's history.
        A SKU with no history simply has no entry.
    """

    org_id: str
    invoice: Dict[str, Any]
    lines: List[Dict[str, Any]] = field(default_factory=list)
    price_baselines: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
