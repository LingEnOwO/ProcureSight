#!/usr/bin/env python3
"""
Main dataset generator for ProcureSight.

Produces:
  - JSON invoices (one file per invoice)
  - CSV invoices (one file per vendor, denormalized)
  - PDF invoices (one file per invoice, multiple templates)

Usage:
    python dataset/generators/generate_dataset.py
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dataset.generators.utils import (
    VENDOR_CATALOG,
    build_invoice,
    generate_invoice_dates,
    make_invoice_no,
    seed_all,
    VendorProfile,
)

# ── Paths ────────────────────────────────────────────────────────────────────

JSON_OUT = ROOT / "dataset/generated/invoices_json"
CSV_OUT  = ROOT / "dataset/generated/invoices_csv"
PDF_OUT  = ROOT / "dataset/generated/invoices_pdf"

SAMPLE_JSON = ROOT / "dataset/sample/invoices_json"
SAMPLE_CSV  = ROOT / "dataset/sample/invoices_csv"
SAMPLE_PDF  = ROOT / "dataset/sample/invoices_pdf"

# ── Constants ────────────────────────────────────────────────────────────────

SEED = 42
HISTORY_MONTHS = 18
LINES_MIN = 5
LINES_MAX = 20
NULL_DUE_DATE_PROB = 0.06   # 6% of invoices omit due_date

# ── PDF template registry ─────────────────────────────────────────────────────

def _pdf_available() -> bool:
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        return False


# ── JSON generation ───────────────────────────────────────────────────────────

def write_json_invoice(invoice: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe = invoice["invoice_no"].replace("/", "_").replace(" ", "_")
    path = directory / f"{safe}.json"
    path.write_text(json.dumps(invoice, indent=2), encoding="utf-8")
    return path


# ── CSV generation ─────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "invoice_no", "vendor", "invoice_date", "due_date", "currency",
    "subtotal", "tax", "total", "sku", "desc", "qty", "unit_price", "line_total",
]


def invoices_to_csv_rows(invoices: list[dict]) -> list[dict]:
    rows = []
    for inv in invoices:
        for line in inv["lines"]:
            rows.append({
                "invoice_no":   inv["invoice_no"],
                "vendor":       inv["vendor"],
                "invoice_date": inv["invoice_date"],
                "due_date":     inv["due_date"] or "",
                "currency":     inv["currency"],
                "subtotal":     inv["subtotal"],
                "tax":          inv["tax"],
                "total":        inv["total"],
                "sku":          line["sku"] or "",
                "desc":         line["desc"],
                "qty":          line["qty"],
                "unit_price":   line["unit_price"],
                "line_total":   line["line_total"],
            })
    return rows


def write_csv_batch(invoices: list[dict], directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    rows = invoices_to_csv_rows(invoices)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


# ── PDF generation ────────────────────────────────────────────────────────────

def _currency_symbol(code: str) -> str:
    return {"USD": "$", "EUR": "€", "JPY": "¥"}.get(code, code + " ")


def _render_pdf_standard(invoice: dict, path: Path) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER

    styles = getSampleStyleSheet()
    sym = _currency_symbol(invoice["currency"])

    doc = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=20,
                                 textColor=colors.HexColor("#1a3c5e"), spaceAfter=4)
    label_style = ParagraphStyle("Label", parent=styles["Normal"], fontSize=9,
                                 textColor=colors.HexColor("#666666"))
    value_style = ParagraphStyle("Value", parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold")
    right_style = ParagraphStyle("Right", parent=styles["Normal"], fontSize=10, alignment=TA_RIGHT)
    right_bold  = ParagraphStyle("RightBold", parent=styles["Normal"], fontSize=11,
                                 fontName="Helvetica-Bold", alignment=TA_RIGHT)

    story = []

    # Header: company name + INVOICE title
    header_data = [
        [
            Paragraph("<b>ProcureSight Corp.</b><br/>123 Business Ave, Suite 400<br/>San Francisco, CA 94105", styles["Normal"]),
            Paragraph("INVOICE", title_style),
        ]
    ]
    header_tbl = Table(header_data, colWidths=[3.5 * inch, 3.5 * inch])
    header_tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 0.15 * inch))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3c5e")))
    story.append(Spacer(1, 0.15 * inch))

    # Invoice meta
    meta_data = [
        [
            Paragraph("Bill To:", label_style),
            "",
            Paragraph("Invoice No:", label_style),
            Paragraph(invoice["invoice_no"], value_style),
        ],
        [
            Paragraph(f"<b>{invoice['vendor']}</b>", styles["Normal"]),
            "",
            Paragraph("Invoice Date:", label_style),
            Paragraph(invoice["invoice_date"], value_style),
        ],
        [
            "",
            "",
            Paragraph("Due Date:", label_style),
            Paragraph(invoice.get("due_date") or "Upon Receipt", value_style),
        ],
        [
            "",
            "",
            Paragraph("Currency:", label_style),
            Paragraph(invoice["currency"], value_style),
        ],
    ]
    meta_tbl = Table(meta_data, colWidths=[2.5 * inch, 1.0 * inch, 1.2 * inch, 2.3 * inch])
    meta_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 0.2 * inch))

    # Line items table
    line_header = ["SKU", "Description", "Qty", f"Unit Price ({sym})", f"Total ({sym})"]
    line_rows = [line_header]
    for ln in invoice["lines"]:
        line_rows.append([
            ln.get("sku") or "—",
            ln["desc"],
            str(ln["qty"]),
            f"{sym}{ln['unit_price']:,.2f}",
            f"{sym}{ln['line_total']:,.2f}",
        ])

    line_tbl = Table(
        line_rows,
        colWidths=[1.0 * inch, 2.9 * inch, 0.6 * inch, 1.2 * inch, 1.3 * inch],
        repeatRows=1,
    )
    line_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, 0), 9),
        ("ALIGN",      (2, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE",   (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4f8")]),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(line_tbl)
    story.append(Spacer(1, 0.15 * inch))

    # Totals
    totals_data = [
        ["", Paragraph("Subtotal:", right_style), Paragraph(f"{sym}{invoice['subtotal']:,.2f}", right_style)],
        ["", Paragraph("Tax:", right_style),      Paragraph(f"{sym}{invoice['tax']:,.2f}", right_style)],
        ["", Paragraph("<b>Total Due:</b>", right_bold), Paragraph(f"<b>{sym}{invoice['total']:,.2f}</b>", right_bold)],
    ]
    totals_tbl = Table(totals_data, colWidths=[4.5 * inch, 1.2 * inch, 1.3 * inch])
    totals_tbl.setStyle(TableStyle([
        ("LINEABOVE", (1, 2), (-1, 2), 1, colors.HexColor("#1a3c5e")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(totals_tbl)

    story.append(Spacer(1, 0.3 * inch))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(
        "Thank you for your business. Please remit payment by the due date.",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8,
                       textColor=colors.HexColor("#888888"), alignment=TA_CENTER),
    ))

    doc.build(story)


def _render_pdf_modern(invoice: dict, path: Path) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT

    styles = getSampleStyleSheet()
    sym = _currency_symbol(invoice["currency"])
    accent = colors.HexColor("#2e7d32")

    doc = SimpleDocTemplate(
        str(path), pagesize=LETTER,
        leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch,
    )

    hdr = ParagraphStyle("H", parent=styles["Heading1"], fontSize=28, textColor=accent, spaceAfter=2)
    sub = ParagraphStyle("S", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#555555"))
    val = ParagraphStyle("V", parent=styles["Normal"], fontSize=10, fontName="Helvetica-Bold")
    rgt = ParagraphStyle("R", parent=styles["Normal"], fontSize=10, alignment=TA_RIGHT)
    rbd = ParagraphStyle("RB", parent=styles["Normal"], fontSize=11, fontName="Helvetica-Bold", alignment=TA_RIGHT)

    story = [
        Paragraph("INVOICE", hdr),
        Paragraph(f"<b>{invoice['vendor']}</b>", styles["Normal"]),
        Spacer(1, 0.05 * inch),
        Paragraph(f"Invoice No: <b>{invoice['invoice_no']}</b> &nbsp;&nbsp; "
                  f"Date: <b>{invoice['invoice_date']}</b> &nbsp;&nbsp; "
                  f"Due: <b>{invoice.get('due_date') or 'Upon Receipt'}</b> &nbsp;&nbsp; "
                  f"Currency: <b>{invoice['currency']}</b>", sub),
        Spacer(1, 0.25 * inch),
    ]

    line_rows = [["SKU", "Description", "Qty", "Unit Price", "Line Total"]]
    for ln in invoice["lines"]:
        line_rows.append([
            ln.get("sku") or "—",
            ln["desc"],
            str(ln["qty"]),
            f"{sym}{ln['unit_price']:,.2f}",
            f"{sym}{ln['line_total']:,.2f}",
        ])

    tbl = Table(line_rows, colWidths=[0.9*inch, 3.0*inch, 0.6*inch, 1.2*inch, 1.3*inch], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), accent),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, accent),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.15 * inch))

    totals = [
        ["", Paragraph("Subtotal:", rgt), Paragraph(f"{sym}{invoice['subtotal']:,.2f}", rgt)],
        ["", Paragraph("Tax:", rgt),      Paragraph(f"{sym}{invoice['tax']:,.2f}", rgt)],
        ["", Paragraph("<b>TOTAL DUE</b>", rbd), Paragraph(f"<b>{sym}{invoice['total']:,.2f}</b>", rbd)],
    ]
    ttbl = Table(totals, colWidths=[4.6*inch, 1.1*inch, 1.3*inch])
    ttbl.setStyle(TableStyle([
        ("LINEABOVE", (1, 2), (-1, 2), 1.5, accent),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(ttbl)

    doc.build(story)


def _render_pdf_compact(invoice: dict, path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch, cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER

    styles = getSampleStyleSheet()
    sym = _currency_symbol(invoice["currency"])

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm,
    )
    hdr = ParagraphStyle("H", parent=styles["Heading2"], fontSize=14, spaceAfter=2)
    sml = ParagraphStyle("S", parent=styles["Normal"], fontSize=8)
    rgt = ParagraphStyle("R", parent=styles["Normal"], fontSize=8, alignment=TA_RIGHT)
    rbd = ParagraphStyle("RB", parent=styles["Normal"], fontSize=9, fontName="Helvetica-Bold", alignment=TA_RIGHT)
    ctr = ParagraphStyle("C", parent=styles["Normal"], fontSize=8, alignment=TA_CENTER)

    story = [
        Paragraph(f"Tax Invoice — {invoice['invoice_no']}", hdr),
        Paragraph(
            f"Vendor: <b>{invoice['vendor']}</b> | Date: {invoice['invoice_date']} | "
            f"Due: {invoice.get('due_date') or 'N/A'} | {invoice['currency']}",
            sml,
        ),
        Spacer(1, 0.1 * inch),
    ]

    line_rows = [["SKU", "Description", "Qty", "Price", "Total"]]
    for ln in invoice["lines"]:
        line_rows.append([
            ln.get("sku") or "—",
            ln["desc"],
            str(ln["qty"]),
            f"{sym}{ln['unit_price']:.2f}",
            f"{sym}{ln['line_total']:.2f}",
        ])
    line_rows += [
        ["", "", "", "Subtotal:", f"{sym}{invoice['subtotal']:.2f}"],
        ["", "", "", "Tax:",      f"{sym}{invoice['tax']:.2f}"],
        ["", "", "", "TOTAL:",    f"{sym}{invoice['total']:.2f}"],
    ]

    col_w = [2.0*cm, 7.5*cm, 1.5*cm, 2.2*cm, 2.5*cm]
    tbl = Table(line_rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -2), 0.3, colors.HexColor("#dddddd")),
        ("LINEABOVE", (3, -3), (-1, -3), 0.5, colors.black),
        ("FONTNAME", (3, -1), (-1, -1), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("E&OE — Please retain for your records.", ctr))

    doc.build(story)


def _add_scan_noise(pdf_path: Path, rng: random.Random) -> None:
    """Simulate a scanned document by converting PDF to image and back."""
    try:
        from PIL import Image, ImageFilter, ImageEnhance
        import importlib
        pdf2image = importlib.import_module("pdf2image")
    except ImportError:
        return  # skip silently if deps not available

    try:
        pages = pdf2image.convert_from_path(str(pdf_path), dpi=150)
    except Exception:
        return

    processed = []
    for page in pages:
        # slight rotation
        angle = rng.uniform(-1.2, 1.2)
        page = page.rotate(angle, expand=False, fillcolor=(255, 255, 255))
        # add subtle noise via contrast + blur
        page = ImageEnhance.Contrast(page).enhance(rng.uniform(0.85, 1.05))
        page = page.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.2, 0.6)))
        # slight brightness variation
        page = ImageEnhance.Brightness(page).enhance(rng.uniform(0.92, 1.05))
        processed.append(page)

    if processed:
        processed[0].save(
            str(pdf_path),
            save_all=True,
            append_images=processed[1:],
            resolution=150,
        )


TEMPLATES = [_render_pdf_standard, _render_pdf_modern, _render_pdf_compact]
SCANNED_PROB = 0.12


def write_pdf_invoice(
    invoice: dict,
    directory: Path,
    template_idx: int,
    rng: random.Random,
    scanned: bool = False,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe = invoice["invoice_no"].replace("/", "_").replace(" ", "_")
    path = directory / f"{safe}.pdf"
    render_fn = TEMPLATES[template_idx % len(TEMPLATES)]
    render_fn(invoice, path)
    if scanned:
        _add_scan_noise(path, rng)
    return path


# ── Main generation loop ───────────────────────────────────────────────────────

def generate(
    json_dir: Path = JSON_OUT,
    csv_dir: Path = CSV_OUT,
    pdf_dir: Path = PDF_OUT,
    sample_json_dir: Path = SAMPLE_JSON,
    sample_csv_dir: Path = SAMPLE_CSV,
    sample_pdf_dir: Path = SAMPLE_PDF,
    seed: int = SEED,
    verbose: bool = True,
) -> list[dict]:
    seed_all(seed)
    rng = random.Random(seed)

    pdf_ok = _pdf_available()
    if not pdf_ok and verbose:
        print("  [warn] reportlab not installed — skipping PDF generation")

    today = date.today()
    history_start = today - timedelta(days=int(HISTORY_MONTHS * 30.44))
    history_end   = today - timedelta(days=1)

    all_invoices: list[dict] = []
    vendor_invoices: dict[str, list[dict]] = {}   # vendor name → invoices (for CSV batching)
    sequence_counter: dict[int, int] = {}

    vendors = VENDOR_CATALOG

    for vi, vendor in enumerate(vendors):
        dates = generate_invoice_dates(vendor, history_start, history_end, rng)
        vendor_invoices[vendor.name] = []

        for inv_date in dates:
            seq = sequence_counter.get(vi, 0) + 1
            sequence_counter[vi] = seq

            invoice_no = make_invoice_no(vi, seq, inv_date.year, rng)
            num_lines  = rng.randint(LINES_MIN, LINES_MAX)
            null_due   = rng.random() < NULL_DUE_DATE_PROB

            invoice = build_invoice(
                vendor, inv_date, invoice_no, rng,
                num_lines=num_lines,
                null_due_date=null_due,
            )

            all_invoices.append(invoice)
            vendor_invoices[vendor.name].append(invoice)

    if verbose:
        print(f"  Generated {len(all_invoices)} invoices across {len(vendors)} vendors")

    # ── Write JSON ────────────────────────────────────────────────────────────
    json_dir.mkdir(parents=True, exist_ok=True)
    for inv in all_invoices:
        write_json_invoice(inv, json_dir)
    if verbose:
        print(f"  Wrote {len(all_invoices)} JSON files → {json_dir}")

    # ── Write CSV (one file per vendor) ───────────────────────────────────────
    csv_dir.mkdir(parents=True, exist_ok=True)
    for vname, invs in vendor_invoices.items():
        if not invs:
            continue
        safe_name = vname.replace(" ", "_").replace("/", "_").replace("&", "and").lower()
        write_csv_batch(invs, csv_dir, f"{safe_name}.csv")
    if verbose:
        print(f"  Wrote {len(vendor_invoices)} CSV files → {csv_dir}")

    # ── Write PDF ─────────────────────────────────────────────────────────────
    if pdf_ok:
        pdf_dir.mkdir(parents=True, exist_ok=True)
        for i, inv in enumerate(all_invoices):
            tmpl_idx = i % len(TEMPLATES)
            scanned  = rng.random() < SCANNED_PROB
            write_pdf_invoice(inv, pdf_dir, tmpl_idx, rng, scanned=scanned)
        if verbose:
            print(f"  Wrote {len(all_invoices)} PDF files → {pdf_dir}")

    # ── Write samples (first few of each type) ────────────────────────────────
    sample_invoices = all_invoices[:5]
    for inv in sample_invoices:
        write_json_invoice(inv, sample_json_dir)

    # Sample CSV: one file with the first 3 vendors combined
    sample_vendors = list(vendor_invoices.keys())[:3]
    sample_csv_invs = []
    for vn in sample_vendors:
        sample_csv_invs.extend(vendor_invoices[vn][:2])
    write_csv_batch(sample_csv_invs, sample_csv_dir, "sample_invoices.csv")

    if pdf_ok:
        for i, inv in enumerate(sample_invoices[:4]):
            write_pdf_invoice(inv, sample_pdf_dir, i % len(TEMPLATES), rng)

    if verbose:
        print(f"  Wrote sample files → {sample_json_dir}, {sample_csv_dir}"
              + (f", {sample_pdf_dir}" if pdf_ok else ""))

    return all_invoices


if __name__ == "__main__":
    print("Generating ProcureSight dataset...")
    invoices = generate(verbose=True)
    print(f"Done. Total invoices: {len(invoices)}")
