"""Which Baseline a line is compared against — the rule, on its own.

No database. `select_price_baseline` is the row selection that used to hide in
`ORDER BY sample_size DESC` plus taking the first row; these pin it as the
behaviour it is. That the rule still agrees with the SQL it replaced is checked
against real Postgres in test_invoice_snapshot_gather.py.
"""
from decimal import Decimal

from apps.api.services.anomaly_scoring import select_price_baseline


def _baseline(desc, sample_size, median):
    return {
        "sku": "WIDGET",
        "desc": desc,
        "sample_size": sample_size,
        "median_unit_price": Decimal(str(median)),
    }


# Ordered the way the snapshot holds them: sample_size descending.
WIDGET = _baseline("Widget", 9, 40)
WIDGET_BLUE = _baseline("WIDGET, blue", 6, 90)
WIDGET_TYPO = _baseline("Widget", 2, 55)
ROWS = [WIDGET, WIDGET_BLUE, WIDGET_TYPO]


def test_no_history_means_no_baseline():
    assert select_price_baseline([], desc="Widget") is None


def test_a_line_compares_against_its_own_description():
    assert select_price_baseline(ROWS, desc="WIDGET, blue") is WIDGET_BLUE


def test_the_best_sampled_row_wins_within_one_description():
    assert select_price_baseline(ROWS, desc="Widget") is WIDGET


def test_a_description_with_no_history_has_no_baseline():
    """It does not fall back to the SKU's other descriptions."""
    assert select_price_baseline(ROWS, desc="widget") is None


def test_a_line_without_a_description_takes_the_best_sampled_row():
    assert select_price_baseline(ROWS, desc=None) is WIDGET


def test_selection_does_not_apply_a_sample_size_threshold():
    """Whether a baseline is well-sampled enough to score against is a separate
    decision, made by the rule that compares prices."""
    thin = _baseline("Widget", 1, 40)

    assert select_price_baseline([thin], desc="Widget") is thin
