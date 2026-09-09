"""The vendor_volume_spike rule, on its own — no database, no bridge shim.

The rows below are shaped exactly as the gathering adapter hands them over (see
``test_invoice_snapshot_gather.py``, which is where the *shape* is checked
against real Postgres); everything here is arithmetic over that shape.

Worth saying why this file carries the weight it does: the golden corpus pins
2,658 invoices' worth of this rule staying *silent*, and not one entry where it
fires — the dataset has no vendor whose spend spikes. So the corpus proves the
rule is quiet where it should be quiet, and these tests are the only thing
holding its severity bands, message text and ``meta`` shape.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.api.models.invoice_snapshot import InvoiceSnapshot
from apps.api.services.anomaly_scoring import (
    score_vendor_volume_spikes,
    select_spend_baseline,
)

ORG = "11111111-1111-5111-8111-111111111111"
VENDOR = "22222222-2222-5222-8222-222222222222"
INVOICE = "33333333-3333-5333-8333-333333333333"
LINE = str(uuid.uuid5(uuid.NAMESPACE_DNS, "volume-spike-line"))


def _line():
    """One line. This rule never reads a line's fields — it only cares that the
    invoice has at least one — so a single anonymous line does for every case."""
    return {
        "id": LINE,
        "invoice_id": INVOICE,
        "sku": "WIDGET",
        "desc": "Widget",
        "qty": Decimal("1"),
        "unit_price": Decimal("8000.00"),
        "line_total": Decimal("8000.00"),
    }


def _spend_baseline(
    *,
    count_30d=8,
    median_30d="1000.00",
    count_90d=12,
    median_90d="1000.00",
):
    return {
        "org_id": ORG,
        "vendor_id": VENDOR,
        "invoice_count_30d": count_30d,
        "total_spend_30d": Decimal("8000.00"),
        "median_invoice_total_30d": None if median_30d is None else Decimal(median_30d),
        "invoice_count_90d": count_90d,
        "total_spend_90d": Decimal("12000.00"),
        "median_invoice_total_90d": None if median_90d is None else Decimal(median_90d),
    }


def _snapshot(*, total="8000.00", lines=None, spend_baselines=None, invoice_no="INV-001"):
    return InvoiceSnapshot(
        org_id=ORG,
        invoice={
            "id": INVOICE,
            "org_id": ORG,
            "vendor_id": VENDOR,
            "invoice_no": invoice_no,
            "invoice_date": date(2026, 5, 12),
            "due_date": date(2026, 6, 11),
            "total": None if total is None else Decimal(total),
        },
        lines=[_line()] if lines is None else lines,
        price_baselines={},
        spend_baselines=[_spend_baseline()] if spend_baselines is None else spend_baselines,
        contract=None,
    )


# ---------------------------------------------------------------------------
# Baseline selection
# ---------------------------------------------------------------------------

def test_no_spend_rows_means_no_baseline():
    assert select_spend_baseline([]) is None


def test_the_first_spend_row_is_the_baseline():
    """The view groups by (org, vendor), so there is at most one — but the
    adapter hands over a list and the choice is stated here rather than assumed."""
    first, second = _spend_baseline(), _spend_baseline(median_90d="2.00")
    assert select_spend_baseline([first, second]) is first


# ---------------------------------------------------------------------------
# Severity bands
# ---------------------------------------------------------------------------

def test_high_severity_at_three_times_the_median():
    alerts = score_vendor_volume_spikes(_snapshot(total="3000.00"))

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.type == "vendor_volume_spike"
    assert alert.severity == "high"
    assert alert.meta["ratio"] == pytest.approx(3.0)


def test_high_severity_well_above_the_median():
    alerts = score_vendor_volume_spikes(_snapshot(total="8000.00"))

    assert alerts[0].severity == "high"
    assert alerts[0].meta["ratio"] == pytest.approx(8.0)
    assert alerts[0].meta["baseline_median_total"] == pytest.approx(1000.0)


def test_medium_severity_between_two_and_three_times():
    alerts = score_vendor_volume_spikes(_snapshot(total="2500.00"))

    assert len(alerts) == 1
    assert alerts[0].severity == "medium"
    assert alerts[0].meta["ratio"] == pytest.approx(2.5)


def test_medium_severity_exactly_at_two_times():
    """The band boundary is inclusive — 2.0x is medium, not silence."""
    alerts = score_vendor_volume_spikes(_snapshot(total="2000.00"))

    assert len(alerts) == 1
    assert alerts[0].severity == "medium"


def test_no_alert_below_the_medium_threshold():
    assert score_vendor_volume_spikes(_snapshot(total="1500.00")) == []


# ---------------------------------------------------------------------------
# Which window the baseline comes from
# ---------------------------------------------------------------------------

def test_the_ninety_day_window_is_preferred_when_it_has_enough_invoices():
    alerts = score_vendor_volume_spikes(
        _snapshot(
            total="8000.00",
            spend_baselines=[_spend_baseline(median_30d="4000.00", median_90d="1000.00")],
        )
    )

    assert alerts[0].meta["baseline_window"] == "90d"
    assert alerts[0].meta["baseline_median_total"] == pytest.approx(1000.0)


def test_the_thirty_day_window_is_the_fallback():
    alerts = score_vendor_volume_spikes(
        _snapshot(
            total="8000.00",
            spend_baselines=[
                _spend_baseline(count_90d=2, median_90d="1000.00", median_30d="2000.00")
            ],
        )
    )

    assert alerts[0].meta["baseline_window"] == "30d"
    assert alerts[0].meta["baseline_median_total"] == pytest.approx(2000.0)


def test_no_alert_when_neither_window_has_enough_invoices():
    """Fewer than MIN_INVOICES_FOR_SPEND_BASELINE either side → no baseline."""
    snapshot = _snapshot(
        total="8000.00",
        spend_baselines=[_spend_baseline(count_30d=4, count_90d=4)],
    )
    assert score_vendor_volume_spikes(snapshot) == []


def test_a_null_ninety_day_median_falls_through_to_the_thirty_day_window():
    """Invoice count and median are checked together, so a 90d window with enough
    invoices but no median does not win — the 30d window is tried next."""
    snapshot = _snapshot(
        total="8000.00",
        spend_baselines=[_spend_baseline(median_90d=None, median_30d="1000.00")],
    )
    alerts = score_vendor_volume_spikes(snapshot)

    assert len(alerts) == 1
    assert alerts[0].meta["baseline_window"] == "30d"


def test_no_alert_when_neither_window_has_a_median():
    snapshot = _snapshot(
        total="8000.00",
        spend_baselines=[_spend_baseline(median_90d=None, median_30d=None)],
    )
    assert score_vendor_volume_spikes(snapshot) == []


def test_no_alert_when_the_median_is_zero():
    snapshot = _snapshot(
        total="8000.00",
        spend_baselines=[_spend_baseline(median_90d="0.00", median_30d="0.00")],
    )
    assert score_vendor_volume_spikes(snapshot) == []


# ---------------------------------------------------------------------------
# Missing data
# ---------------------------------------------------------------------------

def test_no_alert_when_the_vendor_has_no_spend_history():
    assert score_vendor_volume_spikes(_snapshot(spend_baselines=[])) == []


def test_no_alert_when_the_invoice_has_no_total():
    assert score_vendor_volume_spikes(_snapshot(total=None)) == []


def test_an_invoice_with_no_lines_raises_nothing():
    """The joined read this rule used to issue returned no rows for a lineless
    invoice, so the rule stopped before looking at the total. The snapshot makes
    such an invoice representable, and the stop is now explicit."""
    assert score_vendor_volume_spikes(_snapshot(total="8000.00", lines=[])) == []


# ---------------------------------------------------------------------------
# The alert itself
# ---------------------------------------------------------------------------

def test_the_alert_carries_the_ids_and_the_whole_meta_shape():
    alert = score_vendor_volume_spikes(_snapshot(total="8000.00"))[0]

    assert alert.org_id == ORG
    assert alert.invoice_id == INVOICE
    assert alert.vendor_id == VENDOR
    assert alert.meta == {
        "rule": "vendor_volume_spike",
        "ratio": pytest.approx(8.0),
        "baseline_window": "90d",
        "baseline_median_total": pytest.approx(1000.0),
        "invoice_total": pytest.approx(8000.0),
        "invoice_no": "INV-001",
        "invoice_id": INVOICE,
        "vendor_id": VENDOR,
        "counts": {"invoice_count_30d": 8, "invoice_count_90d": 12},
    }


def test_the_message_names_the_total_the_ratio_and_the_window():
    alert = score_vendor_volume_spikes(_snapshot(total="8000.00"))[0]

    assert alert.message == (
        "Invoice total 8000.00 on invoice INV-001 is 8.00x the vendor's "
        "median invoice total over the last 90d."
    )


def test_the_message_falls_back_to_the_invoice_id_when_there_is_no_number():
    alert = score_vendor_volume_spikes(_snapshot(total="8000.00", invoice_no=None))[0]

    assert f"on invoice {INVOICE}" in alert.message
    assert alert.meta["invoice_no"] is None
