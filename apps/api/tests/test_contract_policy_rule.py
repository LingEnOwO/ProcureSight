"""The contract_policy rule, on its own — no database, no bridge shim.

The rows below are shaped exactly as the gathering adapter hands them over (see
``test_invoice_snapshot_gather.py``, which is where the *shape* is checked
against real Postgres); everything here is arithmetic over that shape.

Three sub-rules share one alert type, and each raises its own alert, so most of
what is worth pinning is which of them fired and how many times. As with
``test_volume_spike_rule.py``, the golden corpus only pins this rule's silence —
no dataset vendor has a contract — so the firing paths are held here and nowhere
else.
"""
import itertools
import uuid
from datetime import date
from decimal import Decimal

from apps.api.models.invoice_snapshot import InvoiceSnapshot
from apps.api.services.anomaly_scoring import score_contract_policy_violations

ORG = "11111111-1111-5111-8111-111111111111"
VENDOR = "22222222-2222-5222-8222-222222222222"
INVOICE = "33333333-3333-5333-8333-333333333333"
CONTRACT = "44444444-4444-5444-8444-444444444444"

_line_counter = itertools.count(1)


def _line(*, sku="WID", desc="Widget Assembly"):
    """One invoice line. Each call gets its own id, so two lines alike in every
    other way are still two lines and raise two alerts."""
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"contract-line-{next(_line_counter)}")),
        "invoice_id": INVOICE,
        "sku": sku,
        "desc": desc,
        "qty": Decimal("1"),
        "unit_price": Decimal("500.00"),
        "line_total": Decimal("500.00"),
    }


def _contract(*, spending_limit=None, approved_categories=None, payment_terms_days=None):
    return {
        "id": CONTRACT,
        "spending_limit": None if spending_limit is None else Decimal(spending_limit),
        "approved_categories": approved_categories,
        "payment_terms_days": payment_terms_days,
        "effective_date": date(2026, 1, 1),
        "expiry_date": date(2027, 1, 1),
    }


def _snapshot(
    *,
    contract,
    lines=None,
    total="500.00",
    invoice_no="INV-001",
    invoice_date=date(2026, 5, 12),
    due_date=date(2026, 6, 11),  # 30 days
):
    return InvoiceSnapshot(
        org_id=ORG,
        invoice={
            "id": INVOICE,
            "org_id": ORG,
            "vendor_id": VENDOR,
            "invoice_no": invoice_no,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "total": None if total is None else Decimal(total),
        },
        lines=[_line()] if lines is None else lines,
        price_baselines={},
        spend_baselines=[],
        contract=contract,
    )


def _rules(alerts):
    return [a.meta["rule"] for a in alerts]


# ---------------------------------------------------------------------------
# No contract, no lines
# ---------------------------------------------------------------------------

def test_a_vendor_with_no_contract_has_no_terms_to_violate():
    assert score_contract_policy_violations(_snapshot(contract=None, total="99999.00")) == []


def test_an_invoice_with_no_lines_raises_nothing():
    """Not even the two sub-rules that read only the header. The joined read this
    rule used to issue returned no rows for a lineless invoice, so it stopped
    before reaching the contract; the stop is explicit now."""
    snapshot = _snapshot(
        contract=_contract(spending_limit="1000.00", payment_terms_days=1),
        lines=[],
        total="99999.00",
    )
    assert score_contract_policy_violations(snapshot) == []


def test_a_contract_with_no_terms_set_violates_nothing():
    snapshot = _snapshot(contract=_contract(), total="99999.00")
    assert score_contract_policy_violations(snapshot) == []


# ---------------------------------------------------------------------------
# Sub-rule 1: spending limit
# ---------------------------------------------------------------------------

def test_a_total_over_the_spending_limit_is_high_severity():
    alerts = score_contract_policy_violations(
        _snapshot(contract=_contract(spending_limit="1000.00"), total="5000.00")
    )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.type == "contract_policy_violation"
    assert alert.severity == "high"
    assert alert.meta == {
        "rule": "spending_limit_exceeded",
        "invoice_total": 5000.0,
        "spending_limit": 1000.0,
        "invoice_no": "INV-001",
    }
    assert alert.message == (
        "Invoice INV-001 total 5000.00 exceeds the contract spending limit "
        "of 1000.00 for this vendor."
    )


def test_a_total_exactly_at_the_spending_limit_is_allowed():
    """The comparison is strictly greater-than: spending the whole limit is fine."""
    alerts = score_contract_policy_violations(
        _snapshot(contract=_contract(spending_limit="1000.00"), total="1000.00")
    )
    assert alerts == []


def test_an_invoice_with_no_total_cannot_exceed_the_limit():
    alerts = score_contract_policy_violations(
        _snapshot(contract=_contract(spending_limit="1000.00"), total=None)
    )
    assert alerts == []


# ---------------------------------------------------------------------------
# Sub-rule 2: approved categories
# ---------------------------------------------------------------------------

def test_a_line_matching_no_approved_category_is_high_severity():
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(approved_categories=["office supplies"]),
            lines=[_line(sku="CONS", desc="Premium Consulting")],
        )
    )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.severity == "high"
    assert alert.meta["rule"] == "unapproved_category"
    assert alert.meta["line_desc"] == "Premium Consulting"
    assert alert.meta["line_sku"] == "CONS"
    assert alert.meta["approved_categories"] == ["office supplies"]
    assert alert.message == (
        "Line item 'Premium Consulting' on invoice INV-001 does not match any "
        "approved spend category for this vendor contract."
    )


def test_a_category_matches_as_a_case_insensitive_substring_of_the_line_text():
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(approved_categories=["office supplies"]),
            lines=[_line(sku="PAPER", desc="Office Supplies - Copy Paper")],
        )
    )
    assert alerts == []


def test_the_sku_counts_as_line_text_too():
    """The line text the categories are matched against is desc plus sku."""
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(approved_categories=["widget"]),
            lines=[_line(sku="WIDGET-9", desc="Unlabelled part")],
        )
    )
    assert alerts == []


def test_every_offending_line_raises_its_own_alert():
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(approved_categories=["office supplies"]),
            lines=[
                _line(sku="CONS", desc="Premium Consulting"),
                _line(sku="PAPER", desc="Office Supplies - Copy Paper"),
                _line(sku="TRV", desc="Air Travel"),
            ],
        )
    )

    assert _rules(alerts) == ["unapproved_category", "unapproved_category"]
    assert [a.meta["line_sku"] for a in alerts] == ["CONS", "TRV"]


def test_the_alerts_carry_the_id_of_the_line_that_raised_them():
    lines = [_line(sku="CONS", desc="Premium Consulting")]
    alerts = score_contract_policy_violations(
        _snapshot(contract=_contract(approved_categories=["office supplies"]), lines=lines)
    )

    assert alerts[0].meta["line_id"] == lines[0]["id"]


def test_an_empty_category_list_approves_everything():
    """An empty list is not "nothing is approved" — the sub-rule does not run."""
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(approved_categories=[]),
            lines=[_line(sku="CONS", desc="Premium Consulting")],
        )
    )
    assert alerts == []


def test_a_line_with_neither_desc_nor_sku_matches_nothing_and_is_flagged():
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(approved_categories=["office supplies"]),
            lines=[_line(sku=None, desc=None)],
        )
    )

    assert _rules(alerts) == ["unapproved_category"]
    assert alerts[0].meta["line_desc"] is None
    assert alerts[0].meta["line_sku"] is None
    assert "Line item 'None' on invoice INV-001" in alerts[0].message


# ---------------------------------------------------------------------------
# Sub-rule 3: payment terms
# ---------------------------------------------------------------------------

def test_terms_longer_than_the_contract_allows_are_medium_severity():
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(payment_terms_days=30),
            invoice_date=date(2026, 5, 12),
            due_date=date(2026, 6, 27),  # 46 days
        )
    )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.severity == "medium"
    assert alert.meta == {
        "rule": "payment_terms_violation",
        "actual_days": 46,
        "contracted_days": 30,
        "invoice_date": "2026-05-12",
        "due_date": "2026-06-27",
        "invoice_no": "INV-001",
    }
    assert alert.message == (
        "Invoice INV-001 requests payment in 46 days, exceeding the "
        "contracted payment terms of 30 days."
    )


def test_terms_exactly_at_the_contracted_length_are_allowed():
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(payment_terms_days=30),
            invoice_date=date(2026, 5, 12),
            due_date=date(2026, 6, 11),  # 30 days
        )
    )
    assert alerts == []


def test_an_invoice_with_no_due_date_has_no_terms_to_check():
    alerts = score_contract_policy_violations(
        _snapshot(contract=_contract(payment_terms_days=0), due_date=None)
    )
    assert alerts == []


def test_an_invoice_with_no_invoice_date_has_no_terms_to_check():
    alerts = score_contract_policy_violations(
        _snapshot(contract=_contract(payment_terms_days=0), invoice_date=None)
    )
    assert alerts == []


# ---------------------------------------------------------------------------
# All three together
# ---------------------------------------------------------------------------

def test_one_invoice_can_break_all_three_terms_at_once():
    """Each sub-rule raises separately, and they come back in the order the rule
    checks them — limit, then categories, then terms. The golden corpus pins
    alert order, so this file pins the order within the rule."""
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(
                spending_limit="1000.00",
                approved_categories=["office supplies"],
                payment_terms_days=30,
            ),
            lines=[_line(sku="CONS", desc="Premium Consulting")],
            total="5000.00",
            invoice_date=date(2026, 5, 12),
            due_date=date(2026, 6, 27),
        )
    )

    assert _rules(alerts) == [
        "spending_limit_exceeded",
        "unapproved_category",
        "payment_terms_violation",
    ]
    assert [a.severity for a in alerts] == ["high", "high", "medium"]


def test_an_invoice_inside_every_term_raises_nothing():
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(
                spending_limit="10000.00",
                approved_categories=["widget"],
                payment_terms_days=60,
            ),
            lines=[_line(sku="WID", desc="Widget Assembly")],
            total="500.00",
        )
    )
    assert alerts == []


def test_every_alert_carries_the_invoice_and_vendor_ids():
    alerts = score_contract_policy_violations(
        _snapshot(contract=_contract(spending_limit="1000.00"), total="5000.00")
    )

    assert all(a.org_id == ORG for a in alerts)
    assert all(a.invoice_id == INVOICE for a in alerts)
    assert all(a.vendor_id == VENDOR for a in alerts)


def test_the_messages_fall_back_to_the_invoice_id_when_there_is_no_number():
    alerts = score_contract_policy_violations(
        _snapshot(
            contract=_contract(
                spending_limit="1000.00",
                approved_categories=["office supplies"],
                payment_terms_days=30,
            ),
            lines=[_line(sku="CONS", desc="Premium Consulting")],
            total="5000.00",
            invoice_no=None,
            invoice_date=date(2026, 5, 12),
            due_date=date(2026, 6, 27),
        )
    )

    assert len(alerts) == 3
    assert all(INVOICE in a.message for a in alerts)
    assert all(a.meta["invoice_no"] is None for a in alerts)
