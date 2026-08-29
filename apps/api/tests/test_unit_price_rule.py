"""The unit_price_delta rule, on its own — no database, no bridge shim.

Asking "does a unit price three times the Baseline median raise a high-severity
Alert?" is now a snapshot literal and a function call. The rows below are shaped
exactly as the gathering adapter hands them over (see
``test_invoice_snapshot_gather.py``, which is where the *shape* is checked
against real Postgres); everything here is arithmetic over that shape.
"""
import itertools
import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.api.models.invoice_snapshot import InvoiceSnapshot
from apps.api.services.anomaly_scoring import score_unit_price_deltas

ORG = "11111111-1111-5111-8111-111111111111"
VENDOR = "22222222-2222-5222-8222-222222222222"
INVOICE = "33333333-3333-5333-8333-333333333333"


_line_counter = itertools.count(1)


def _line(*, sku="WIDGET", desc="Widget", unit_price="200"):
    """One invoice line. Each call gets its own id, so two lines that are alike
    in every other way are still two lines and raise two alerts."""
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"line-{next(_line_counter)}")),
        "invoice_id": INVOICE,
        "sku": sku,
        "desc": desc,
        "qty": Decimal("1"),
        "unit_price": None if unit_price is None else Decimal(unit_price),
        "line_total": None if unit_price is None else Decimal(unit_price),
    }


def _baseline(*, sku="WIDGET", desc="Widget", sample_size=6, median="40"):
    return {
        "org_id": ORG,
        "vendor_id": VENDOR,
        "sku": sku,
        "desc": desc,
        "sample_size": sample_size,
        "median_unit_price": None if median is None else Decimal(median),
        "mean_unit_price": None if median is None else Decimal(median),
    }


def _snapshot(*, lines=None, price_baselines=None, invoice_no="INV-001", total="1.00"):
    return InvoiceSnapshot(
        org_id=ORG,
        invoice={
            "id": INVOICE,
            "org_id": ORG,
            "vendor_id": VENDOR,
            "invoice_no": invoice_no,
            "invoice_date": date(2026, 5, 12),
            "due_date": date(2026, 6, 11),
            "total": Decimal(total),
        },
        lines=[_line()] if lines is None else lines,
        price_baselines={"WIDGET": [_baseline()]} if price_baselines is None else price_baselines,
    )


# ── The severity ladder ──────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "unit_price, severity, ratio",
    [
        ("200", "high", 5.0),     # 5x   → high
        ("120", "high", 3.0),     # 3x   → the high boundary
        ("100", "medium", 2.5),   # 2.5x → medium
        ("80", "medium", 2.0),    # 2x   → the medium boundary
        ("70", "low", 1.75),      # 1.75x → low
        ("60", "low", 1.5),       # 1.5x → the low boundary
    ],
)
def test_the_severity_ladder(unit_price, severity, ratio):
    out = score_unit_price_deltas(_snapshot(lines=[_line(unit_price=unit_price)]))

    assert len(out) == 1
    assert out[0].type == "unit_price_delta"
    assert out[0].severity == severity
    assert out[0].meta["ratio"] == pytest.approx(ratio)


def test_below_the_low_threshold_raises_nothing():
    assert score_unit_price_deltas(_snapshot(lines=[_line(unit_price="50")])) == []  # 1.25x


# ── When the rule declines to score ──────────────────────────────────────────

def test_a_thinly_sampled_baseline_is_not_worth_comparing_against():
    """Below MIN_SAMPLE_SIZE_FOR_BASELINE the median is noise, however extreme
    the ratio."""
    snapshot = _snapshot(
        lines=[_line(unit_price="400")],
        price_baselines={"WIDGET": [_baseline(sample_size=4)]},
    )
    assert score_unit_price_deltas(snapshot) == []


def test_a_sku_with_no_history_raises_nothing():
    assert score_unit_price_deltas(_snapshot(price_baselines={})) == []


def test_a_line_with_no_sku_names_no_purchased_item():
    assert score_unit_price_deltas(_snapshot(lines=[_line(sku=None)])) == []


def test_a_line_with_no_unit_price_cannot_be_compared():
    assert score_unit_price_deltas(_snapshot(lines=[_line(unit_price=None)])) == []


@pytest.mark.parametrize("median", [None, "0"])
def test_a_non_positive_median_is_no_baseline_at_all(median):
    snapshot = _snapshot(price_baselines={"WIDGET": [_baseline(median=median)]})
    assert score_unit_price_deltas(snapshot) == []


def test_an_invoice_with_no_lines_raises_nothing():
    assert score_unit_price_deltas(_snapshot(lines=[])) == []


# ── Which baseline a line is compared against ────────────────────────────────

def test_a_line_compares_against_its_own_description():
    """Two variants under one SKU; the better-sampled one is not the line's."""
    snapshot = _snapshot(
        lines=[_line(desc="WIDGET, blue", unit_price="200")],
        price_baselines={
            "WIDGET": [
                _baseline(desc="Widget", sample_size=9, median="40"),
                _baseline(desc="WIDGET, blue", sample_size=6, median="90"),
            ]
        },
    )

    out = score_unit_price_deltas(snapshot)

    assert len(out) == 1
    assert out[0].meta["median_unit_price"] == Decimal("90")
    assert out[0].meta["sample_size"] == 6


def test_a_description_with_no_history_has_no_baseline_to_compare_against():
    snapshot = _snapshot(
        lines=[_line(desc="widget")],
        price_baselines={"WIDGET": [_baseline(desc="Widget")]},
    )
    assert score_unit_price_deltas(snapshot) == []


# ── One alert per offending line ─────────────────────────────────────────────

def test_each_offending_line_raises_its_own_alert():
    lines = [
        _line(sku="WIDGET", desc="Widget", unit_price="200"),   # 5x
        _line(sku="BOLT", desc="Bolt", unit_price="50"),        # 1.25x — quiet
        _line(sku="NUT", desc="Nut", unit_price="30"),          # 3x
    ]
    snapshot = _snapshot(
        lines=lines,
        price_baselines={
            "WIDGET": [_baseline(sku="WIDGET", desc="Widget", median="40")],
            "BOLT": [_baseline(sku="BOLT", desc="Bolt", median="40")],
            "NUT": [_baseline(sku="NUT", desc="Nut", median="10")],
        },
    )

    out = score_unit_price_deltas(snapshot)

    assert [c.meta["sku"] for c in out] == ["WIDGET", "NUT"]
    assert [c.meta["line_id"] for c in out] == [str(lines[0]["id"]), str(lines[2]["id"])]


# ── The shape an operator and the alerts table see ───────────────────────────

def test_the_message_and_meta_are_what_downstream_reads():
    line = _line(unit_price="200")
    out = score_unit_price_deltas(_snapshot(lines=[line]))

    assert out[0].message == (
        "Unit price 200.00 for SKU 'WIDGET' on invoice INV-001 is 5.00x the "
        "historical median price (40.00) for this vendor."
    )
    assert out[0].meta == {
        "rule": "unit_price_delta_vs_median",
        "ratio": 5.0,
        "median_unit_price": Decimal("40"),
        "unit_price": 200.0,
        "sample_size": 6,
        "sku": "WIDGET",
        "desc": "Widget",
        "invoice_no": "INV-001",
        "invoice_id": INVOICE,
        "vendor_id": VENDOR,
        "line_id": str(line["id"]),
    }
    assert (out[0].org_id, out[0].invoice_id, out[0].vendor_id) == (ORG, INVOICE, VENDOR)


def test_an_invoice_with_no_number_falls_back_to_its_id_in_the_message():
    out = score_unit_price_deltas(_snapshot(invoice_no=None))

    assert f"on invoice {INVOICE} is" in out[0].message
    assert out[0].meta["invoice_no"] is None
