from typing import List
from ..models.invoice import Invoice
from ..models.validation import ValidationIssue ,ValidationReport

# Tolerances (in invoice currency units, typically dollars)
LINE_TOLERANCE = 0.02   # up to 2 cents rounding difference is acceptable as warning
TOTAL_TOLERANCE = 0.02  # same for subtotal / total reconciliation


def validate_invoice(inv: Invoice) -> ValidationReport:
    """
    Perform business-level validation on an Invoice that has already passed
    schema validation.

    This checks:
    - Per-line math: qty * unit_price ≈ line_total
    - Subtotal: sum(line_total) ≈ subtotal
    - Total: subtotal + tax ≈ total

    Small rounding differences are emitted as warnings; larger gaps become
    hard errors. The returned ValidationReport includes a normalized_invoice
    which may have tiny auto-corrections applied (e.g., line_total adjusted
    to the recomputed value when within tolerance).
    """
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []

    # Work on a normalized copy so we can safely adjust values without mutating the input
    norm_inv = inv.model_copy(deep=True)

    # 1) Validate and optionally normalize each line item
    normalized_lines = []
    for idx, line in enumerate(norm_inv.lines):
        try:
            expected_line_total = round(float(line.qty) * float(line.unit_price), 2)
        except Exception:
            # If we cannot compute, treat as a hard error on that line
            errors.append(
                ValidationIssue(
                    field=f"lines[{idx}]",
                    code="LINE_CALCULATION_ERROR",
                    message="Unable to compute line_total from qty and unit_price.",
                )
            )
            normalized_lines.append(line)
            continue

        diff = abs(expected_line_total - float(line.line_total))

        if diff > LINE_TOLERANCE:
            # Hard mismatch: likely a bad extraction
            errors.append(
                ValidationIssue(
                    field=f"lines[{idx}].line_total",
                    code="LINE_TOTAL_MISMATCH",
                    message=(
                        f"line_total differs from qty * unit_price "
                        f"by {diff:.2f} (expected {expected_line_total:.2f}, "
                        f"got {float(line.line_total):.2f})."
                    ),
                    diff=diff,
                )
            )
            normalized_lines.append(line)
        elif diff > 0:
            # Within tolerance: warn and normalize the value to the recomputed total
            warnings.append(
                ValidationIssue(
                    field=f"lines[{idx}].line_total",
                    code="LINE_TOTAL_ROUNDING_ADJUSTED",
                    message=(
                        f"line_total adjusted from {float(line.line_total):.2f} "
                        f"to {expected_line_total:.2f} due to minor rounding difference."
                    ),
                    diff=diff,
                )
            )
            normalized_lines.append(
                line.model_copy(update={"line_total": expected_line_total})
            )
        else:
            normalized_lines.append(line)

    norm_inv = norm_inv.model_copy(update={"lines": normalized_lines})

    # 2) Validate subtotal vs sum of line totals
    computed_subtotal = round(
        sum(float(line.line_total) for line in norm_inv.lines),
        2,
    )
    diff_subtotal = abs(computed_subtotal - float(norm_inv.subtotal))

    if diff_subtotal > TOTAL_TOLERANCE:
        errors.append(
            ValidationIssue(
                field="subtotal",
                code="SUBTOTAL_MISMATCH",
                message=(
                    f"subtotal differs from sum of line totals by {diff_subtotal:.2f} "
                    f"(expected {computed_subtotal:.2f}, got {float(norm_inv.subtotal):.2f})."
                ),
                diff=diff_subtotal,
            )
        )
    elif diff_subtotal > 0:
        warnings.append(
            ValidationIssue(
                field="subtotal",
                code="SUBTOTAL_ROUNDING_ADJUSTED",
                message=(
                    f"subtotal adjusted from {float(norm_inv.subtotal):.2f} "
                    f"to {computed_subtotal:.2f} due to minor rounding difference."
                ),
                diff=diff_subtotal,
            )
        )
        norm_inv = norm_inv.model_copy(update={"subtotal": computed_subtotal})

    # 3) Validate total vs subtotal + tax
    tax_value = float(norm_inv.tax or 0)
    expected_total = round(float(norm_inv.subtotal) + tax_value, 2)
    diff_total = abs(expected_total - float(norm_inv.total))

    if diff_total > TOTAL_TOLERANCE:
        errors.append(
            ValidationIssue(
                field="total",
                code="TOTAL_MISMATCH",
                message=(
                    f"total differs from subtotal + tax by {diff_total:.2f} "
                    f"(expected {expected_total:.2f}, got {float(norm_inv.total):.2f})."
                ),
                diff=diff_total,
            )
        )
    elif diff_total > 0:
        warnings.append(
            ValidationIssue(
                field="total",
                code="TOTAL_ROUNDING_ADJUSTED",
                message=(
                    f"total adjusted from {float(norm_inv.total):.2f} "
                    f"to {expected_total:.2f} due to minor rounding difference."
                ),
                diff=diff_total,
            )
        )
        norm_inv = norm_inv.model_copy(update={"total": expected_total})

    return ValidationReport(
        errors=errors,
        warnings=warnings,
        normalized_invoice=norm_inv,
    )
