"""
Characterization tests for invoice validation and confidence scoring.

validate_invoice() reconciles line math, subtotal, and total, emitting warnings
for sub-tolerance rounding (which it auto-normalizes) and hard errors for larger
gaps. These tests pin down:

  * the ±0.02 tolerance boundary (exactly 0.02 → warning; above → error),
  * the auto-normalization of within-tolerance values,
  * that errored values are NOT normalized,
  * the confidence math (overall + per-field) and the needs_review gate.

This is pure logic (no DB) and touches financial correctness, so behavior must
not drift silently during the planned validator refactor.

Boundary note: because 0.02 has no exact float representation, a "2 cent" diff
computes as ~0.0199999 and is classified as a warning (`diff > 0.02` is False).
This is the current, intended behavior and is asserted explicitly below.
"""
from datetime import date
from decimal import Decimal

import pytest

from apps.api.models.invoice import Invoice, InvoiceLine
from apps.api.models.validation import ValidationIssue, ValidationReport
from apps.api.services.validator import (
    validate_invoice,
    compute_invoice_confidence,
    compute_field_confidence,
    needs_review,
    WARNING_PENALTY,
    MIN_CONFIDENCE_WITH_WARNINGS,
)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _line(desc="Widget", qty="1", unit_price="10.00", line_total="10.00", sku=None):
    return InvoiceLine(
        sku=sku,
        desc=desc,
        qty=Decimal(qty),
        unit_price=Decimal(unit_price),
        line_total=Decimal(line_total),
    )


def _invoice(lines=None, subtotal="10.00", tax="0", total="10.00"):
    if lines is None:
        lines = [_line()]
    return Invoice(
        vendor="Acme",
        invoice_no="INV-1",
        invoice_date=date(2024, 1, 1),
        currency="USD",
        subtotal=Decimal(subtotal),
        tax=Decimal(tax),
        total=Decimal(total),
        lines=lines,
    )


def _issue(field, code="X"):
    return ValidationIssue(field=field, code=code, message="m")


def _report(errors=None, warnings=None):
    """Synthetic report for unit-testing the confidence helpers directly."""
    return ValidationReport(
        errors=errors or [],
        warnings=warnings or [],
        normalized_invoice=_invoice(),
    )


def _codes(report):
    return [i.code for i in report.errors + report.warnings]


# ===========================================================================
# Clean invoice
# ===========================================================================

def test_clean_invoice_has_no_issues():
    report = validate_invoice(
        _invoice(lines=[_line(qty="2", unit_price="10.00", line_total="20.00")],
                 subtotal="20.00", tax="0", total="20.00")
    )
    assert report.errors == []
    assert report.warnings == []
    assert compute_invoice_confidence(report) == 1.0
    assert needs_review(report) is False


def test_tax_is_added_into_total():
    report = validate_invoice(
        _invoice(lines=[_line(qty="2", unit_price="10.00", line_total="20.00")],
                 subtotal="20.00", tax="2.00", total="22.00")
    )
    assert report.errors == []
    assert report.warnings == []


# ===========================================================================
# Per-line math + tolerance boundary
# ===========================================================================

def test_line_rounding_within_tolerance_warns_and_normalizes():
    """A 1-cent line discrepancy is a warning and the value is normalized."""
    report = validate_invoice(_invoice(lines=[_line(line_total="10.01")]))
    assert _codes(report) == ["LINE_TOTAL_ROUNDING_ADJUSTED"]
    # normalized down to the recomputed 1 * 10.00 = 10.00
    assert float(report.normalized_invoice.lines[0].line_total) == pytest.approx(10.00)


def test_line_diff_of_exactly_two_cents_is_a_warning_not_error():
    """The tolerance boundary: a 2-cent diff stays a warning (diff > 0.02 is False)."""
    report = validate_invoice(_invoice(lines=[_line(line_total="10.02")]))
    assert _codes(report) == ["LINE_TOTAL_ROUNDING_ADJUSTED"]


def test_line_diff_above_tolerance_is_error_and_not_normalized():
    """A 3-cent diff is a hard error; the bad value is retained, not corrected.

    subtotal/total are set to match the bad line so this isolates the line error
    (an errored line is not normalized, which would otherwise cascade into a
    subtotal mismatch — see test below).
    """
    report = validate_invoice(
        _invoice(lines=[_line(line_total="10.03")], subtotal="10.03", total="10.03")
    )
    assert _codes(report) == ["LINE_TOTAL_MISMATCH"]
    assert report.has_errors is True
    issue = report.errors[0]
    assert issue.field == "lines[0].line_total"
    assert issue.diff == pytest.approx(0.03, abs=1e-6)
    # value is preserved, NOT normalized
    assert float(report.normalized_invoice.lines[0].line_total) == pytest.approx(10.03)
    # confidence collapses on any error
    assert compute_invoice_confidence(report) == 0.0
    assert needs_review(report) is True


def test_errored_line_cascades_into_subtotal_mismatch():
    """Because errored lines aren't normalized, a 'correct' subtotal no longer
    reconciles — documents the current cascade behavior."""
    report = validate_invoice(
        _invoice(lines=[_line(line_total="10.05")], subtotal="10.00", total="10.00")
    )
    assert set(_codes(report)) == {"LINE_TOTAL_MISMATCH", "SUBTOTAL_MISMATCH"}


# ===========================================================================
# Subtotal reconciliation
# ===========================================================================

def test_subtotal_rounding_warns_and_normalizes():
    report = validate_invoice(
        _invoice(lines=[_line(line_total="10.00")], subtotal="10.01", total="10.00")
    )
    assert _codes(report) == ["SUBTOTAL_ROUNDING_ADJUSTED"]
    assert float(report.normalized_invoice.subtotal) == pytest.approx(10.00)


def test_subtotal_mismatch_is_error():
    report = validate_invoice(
        _invoice(lines=[_line(line_total="10.00")], subtotal="25.00", total="25.00")
    )
    assert "SUBTOTAL_MISMATCH" in _codes(report)
    assert report.has_errors is True


# ===========================================================================
# Total reconciliation
# ===========================================================================

def test_total_rounding_warns_and_normalizes():
    report = validate_invoice(
        _invoice(lines=[_line(line_total="10.00")], subtotal="10.00", tax="0", total="10.01")
    )
    assert _codes(report) == ["TOTAL_ROUNDING_ADJUSTED"]
    assert float(report.normalized_invoice.total) == pytest.approx(10.00)


def test_total_mismatch_is_error():
    report = validate_invoice(
        _invoice(lines=[_line(line_total="10.00")], subtotal="10.00", tax="0", total="25.00")
    )
    assert "TOTAL_MISMATCH" in _codes(report)
    assert report.has_errors is True


# ===========================================================================
# compute_invoice_confidence (direct, with synthetic reports)
# ===========================================================================

def test_confidence_is_one_with_no_issues():
    assert compute_invoice_confidence(_report()) == 1.0


def test_confidence_drops_by_penalty_per_warning():
    assert compute_invoice_confidence(_report(warnings=[_issue("a")])) == pytest.approx(1.0 - WARNING_PENALTY)
    assert compute_invoice_confidence(
        _report(warnings=[_issue("a"), _issue("b")])
    ) == pytest.approx(1.0 - 2 * WARNING_PENALTY)


def test_confidence_clamped_to_floor_with_many_warnings():
    many = [_issue(f"f{i}") for i in range(20)]  # 1 - 1.0 = -0.0, clamps up
    assert compute_invoice_confidence(_report(warnings=many)) == MIN_CONFIDENCE_WITH_WARNINGS


def test_confidence_is_zero_with_any_error_regardless_of_warnings():
    report = _report(errors=[_issue("total")], warnings=[_issue("a")])
    assert compute_invoice_confidence(report) == 0.0


# ===========================================================================
# compute_field_confidence
# ===========================================================================

def test_field_confidence_warning_and_error():
    report = _report(
        warnings=[_issue("subtotal", "SUBTOTAL_ROUNDING_ADJUSTED")],
        errors=[_issue("total", "TOTAL_MISMATCH")],
    )
    conf = compute_field_confidence(report)
    assert conf["subtotal"] == pytest.approx(0.95)
    assert conf["total"] == 0.0
    # untouched fields are not present in the dict
    assert "tax" not in conf


def test_field_confidence_error_overrides_warning_on_same_field():
    report = _report(
        warnings=[_issue("total", "W")],
        errors=[_issue("total", "E")],
    )
    assert compute_field_confidence(report)["total"] == 0.0


# ===========================================================================
# needs_review
# ===========================================================================

def test_needs_review_true_on_errors():
    assert needs_review(_report(errors=[_issue("total")])) is True


def test_needs_review_false_when_confidence_at_or_above_threshold():
    # 2 warnings → 0.90, which is NOT below the default 0.9 threshold
    assert needs_review(_report(warnings=[_issue("a"), _issue("b")])) is False


def test_needs_review_true_when_confidence_below_threshold():
    # 3 warnings → 0.85 < 0.9
    assert needs_review(_report(warnings=[_issue("a"), _issue("b"), _issue("c")])) is True


def test_needs_review_respects_custom_threshold():
    # 1 warning → 0.95; below a strict 1.0 threshold
    assert needs_review(_report(warnings=[_issue("a")]), threshold=1.0) is True
