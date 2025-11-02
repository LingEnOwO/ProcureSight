#!/usr/bin/env python3
"""
make_fake_invoices.py

Generate synthetic invoice datasets for ProcureSight.
- Structured outputs: CSV and/or JSON
- Optional unstructured outputs: simple PDF invoices (for OCR tests)
- Edge cases: duplicates, mixed currencies, rounding quirks, long invoices

Usage examples:
  python scripts/make_fake_invoices.py \
    --csv data/samples/invoices_csv \
    --json data/samples/invoices_json \
    --pdf data/samples/invoices_pdf \
    --contracts data/samples/contracts_pdf \
    --n 12

Dependencies:
  pip install faker pandas reportlab (reportlab only needed for --pdf/--contracts)

This script is deterministic per --seed to make debugging easier.
"""
from __future__ import annotations
import argparse
import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from random import Random
from typing import List

try:
    from faker import Faker
except Exception as e:
    raise SystemExit("Please install 'faker' (pip install faker)")

try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None  # CSV writing will fallback to Python csv if pandas missing

try:
    # Only needed for PDFs
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas as pdf_canvas
except Exception:
    LETTER = None
    inch = None
    pdf_canvas = None

import csv

SUPPORTED_CURRENCIES = [
    ("USD", 1.0),
    ("EUR", 0.92),
    ("JPY", 150.0),
]

VENDOR_POOL = [
    "Apex Office Supply", "NovaTech Components", "BlueRiver Logistics",
    "Summit Paper Co.", "Cedar Industrial Tools", "Orion IT Services",
    "Maple Catering", "EverGreen Janitorial", "Vertex Printing",
]

SKU_POOL = [
    ("PPR-A4-500", "Copy Paper A4 500 sheets"),
    ("INK-XL-BLK", "Ink Cartridge XL Black"),
    ("PNC-GEL-12", "Gel Pens 0.7mm (12pk)"),
    ("NTE-ETH-5M", "Cat6 Ethernet Cable 5m"),
    ("MON-27FHD", "27\" IPS Monitor 1080p"),
    ("MSE-WRL-02", "Wireless Mouse"),
    ("KBD-MEC-87", "Mechanical Keyboard TKL"),
    ("CLN-WIPES", "Electronics Cleaning Wipes (50)"),
    ("BRK-COFF-1K", "Coffee Beans 1kg"),
]

@dataclass
class LineItem:
    sku: str
    desc: str
    qty: int
    unit_price: float
    @property
    def line_total(self) -> float:
        return round(self.qty * self.unit_price, 2)

@dataclass
class Invoice:
    invoice_no: str
    vendor: str
    date: str  # ISO yyyy-mm-dd
    currency: str
    subtotal: float
    tax: float
    total: float
    lines: List[LineItem]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def make_invoice_number(rng: Random, vendor_index: int, counter: int) -> str:
    # e.g., INV-APX-202509-0142
    return f"INV-{vendor_index:02d}-{date.today().strftime('%Y%m')}-{counter:04d}"


def random_line_item(rng: Random) -> LineItem:
    sku, desc = rng.choice(SKU_POOL)
    qty = rng.randint(1, 12)
    # base price with some variance
    base = {
        "PPR-A4-500": 5.99,
        "INK-XL-BLK": 38.0,
        "PNC-GEL-12": 9.5,
        "NTE-ETH-5M": 8.0,
        "MON-27FHD": 159.0,
        "MSE-WRL-02": 19.0,
        "KBD-MEC-87": 79.0,
        "CLN-WIPES": 6.0,
        "BRK-COFF-1K": 14.0,
    }[sku]
    unit_price = round(base * (0.85 + rng.random() * 0.4), 2)  # ±15% to +25%
    return LineItem(sku=sku, desc=desc, qty=qty, unit_price=unit_price)


def build_invoice(rng: Random, fake: Faker, vendor: str, vendor_index: int, idx: int,
                  currency: str) -> Invoice:
    # date spread over last ~120 days
    d = date.today() - timedelta(days=rng.randint(0, 120))
    # 5–20 line items; sometimes 25+ for a stress test
    n_items = 5 + rng.randint(0, 15)
    if rng.random() < 0.2:
        n_items += rng.randint(5, 20)  # occasional long invoice

    items = [random_line_item(rng) for _ in range(n_items)]
    subtotal = round(sum(li.line_total for li in items), 2)

    # Occasionally inject rounding funkiness
    if rng.random() < 0.1:
        subtotal = float(f"{subtotal:.3f}")  # extra precision to test rounding

    # tax between 0% and 10%
    tax_rate = rng.choice([0.0, 0.05, 0.07, 0.1])
    tax = round(subtotal * tax_rate, 2)

    total = round(subtotal + tax, 2)

    inv = Invoice(
        invoice_no=make_invoice_number(rng, vendor_index, idx),
        vendor=vendor,
        date=d.isoformat(),
        currency=currency,
        subtotal=float(f"{subtotal:.2f}") if isinstance(subtotal, float) else subtotal,
        tax=tax,
        total=total,
        lines=items,
    )

    # Sometimes insert a credit line (negative) as an edge case
    if rng.random() < 0.08:
        credit = LineItem(sku="CREDIT", desc="Promotional credit", qty=1, unit_price=-round(rng.uniform(5, 25), 2))
        inv.lines.append(credit)
        inv.subtotal = round(inv.subtotal + credit.line_total, 2)
        inv.total = round(inv.subtotal + inv.tax, 2)

    return inv


def maybe_duplicate_invoice(rng: Random, inv: Invoice) -> Invoice:
    """Create a near-duplicate invoice (same vendor+invoice_no, slight total diff)."""
    # Make a shallow copy of the dataclass while *deep*-copying the list of LineItem
    # objects so that edits to the duplicate do not modify the original invoice.
    dup = replace(
        inv,
        lines=[LineItem(li.sku, li.desc, li.qty, li.unit_price) for li in inv.lines],
    )

    # Tiny change to one line to simulate near-duplicate / correction
    if dup.lines:
        i = rng.randrange(len(dup.lines))
        li = dup.lines[i]
        li.unit_price = round(li.unit_price * (1.0 + (rng.random() - 0.5) * 0.02), 2)  # ±1%

    dup.subtotal = round(sum(li.line_total for li in dup.lines), 2)
    dup.total = round(dup.subtotal + dup.tax, 2)
    return dup


def write_csv(out_dir: Path, invoices: List[Invoice]) -> None:
    ensure_dir(out_dir)
    inv_path = out_dir / "invoices.csv"
    line_path = out_dir / "invoice_lines.csv"

    # invoices.csv
    with open(inv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["invoice_no", "vendor", "date", "currency", "subtotal", "tax", "total"])
        for inv in invoices:
            w.writerow([inv.invoice_no, inv.vendor, inv.date, inv.currency, f"{inv.subtotal:.2f}", f"{inv.tax:.2f}", f"{inv.total:.2f}"])

    # invoice_lines.csv
    with open(line_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["invoice_no", "sku", "desc", "qty", "unit_price", "line_total"])
        for inv in invoices:
            for li in inv.lines:
                w.writerow([inv.invoice_no, li.sku, li.desc, li.qty, f"{li.unit_price:.2f}", f"{li.line_total:.2f}"])


def write_json(out_dir: Path, invoices: List[Invoice]) -> None:
    ensure_dir(out_dir)
    for inv in invoices:
        path = out_dir / f"{inv.invoice_no}.json"
        payload = {
            "invoice_no": inv.invoice_no,
            "vendor": inv.vendor,
            "date": inv.date,
            "currency": inv.currency,
            "subtotal": round(inv.subtotal, 2),
            "tax": round(inv.tax, 2),
            "total": round(inv.total, 2),
            "lines": [
                {
                    "sku": li.sku,
                    "desc": li.desc,
                    "qty": li.qty,
                    "unit_price": round(li.unit_price, 2),
                    "line_total": round(li.line_total, 2),
                }
                for li in inv.lines
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)


def draw_pdf_invoice(path: Path, inv: Invoice) -> None:
    if pdf_canvas is None or LETTER is None or inch is None:
        raise RuntimeError("reportlab not installed; cannot generate PDFs. 'pip install reportlab' or omit --pdf")
    c = pdf_canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1*inch, height - 1*inch, "INVOICE")

    c.setFont("Helvetica", 10)
    c.drawString(1*inch, height - 1.3*inch, f"Invoice No: {inv.invoice_no}")
    c.drawString(1*inch, height - 1.5*inch, f"Vendor: {inv.vendor}")
    c.drawString(1*inch, height - 1.7*inch, f"Date: {inv.date}")
    c.drawString(1*inch, height - 1.9*inch, f"Currency: {inv.currency}")

    # Table header
    y = height - 2.3*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(1*inch, y, "SKU")
    c.drawString(2.7*inch, y, "Description")
    c.drawString(5.2*inch, y, "Qty")
    c.drawString(5.7*inch, y, "Unit")
    c.drawString(6.4*inch, y, "Total")
    y -= 0.2*inch
    c.line(1*inch, y, 7.5*inch, y)
    y -= 0.1*inch

    c.setFont("Helvetica", 10)
    for li in inv.lines:
        if y < 1.5*inch:
            c.showPage()
            y = height - 1*inch
        c.drawString(1*inch, y, li.sku[:12])
        c.drawString(2.7*inch, y, li.desc[:34])
        c.drawRightString(5.4*inch, y, str(li.qty))
        c.drawRightString(6.3*inch, y, f"{li.unit_price:.2f}")
        c.drawRightString(7.5*inch, y, f"{li.line_total:.2f}")
        y -= 0.18*inch

    # Totals
    y -= 0.1*inch
    c.line(5.8*inch, y, 7.5*inch, y)
    y -= 0.18*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(6.8*inch, y, "Subtotal:")
    c.setFont("Helvetica", 10)
    c.drawRightString(7.5*inch, y, f"{inv.subtotal:.2f}")
    y -= 0.18*inch
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(6.8*inch, y, "Tax:")
    c.setFont("Helvetica", 10)
    c.drawRightString(7.5*inch, y, f"{inv.tax:.2f}")
    y -= 0.18*inch
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(6.8*inch, y, "Total:")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(7.5*inch, y, f"{inv.total:.2f}")

    c.showPage()
    c.save()


def write_pdfs(out_dir: Path, invoices: List[Invoice]) -> None:
    ensure_dir(out_dir)
    for inv in invoices:
        path = out_dir / f"{inv.invoice_no}.pdf"
        draw_pdf_invoice(path, inv)


def write_contract_pdfs(out_dir: Path, rng: Random, n: int = 3) -> None:
    if pdf_canvas is None or LETTER is None or inch is None:
        print("[warn] reportlab not installed; skipping contract PDFs")
        return
    ensure_dir(out_dir)
    for i in range(n):
        path = out_dir / f"ContractTemplate-{i+1:02d}.pdf"
        c = pdf_canvas.Canvas(str(path), pagesize=LETTER)
        width, height = LETTER
        c.setFont("Helvetica-Bold", 14)
        c.drawString(1*inch, height - 1*inch, "Service Agreement")
        c.setFont("Helvetica", 10)
        lorem = (
            "This Service Agreement (the 'Agreement') is made between Client and Vendor. "
            "The parties agree to the following terms, including payment, deliverables, and termination. "
            "Governing law shall be the state specified in the Order Form."
        )
        y = height - 1.4*inch
        for line in wrap_text(lorem, width - 2*inch, pdf_canvas):
            c.drawString(1*inch, y, line)
            y -= 0.18*inch
        c.drawString(1*inch, y-0.4*inch, "Signature: _________________________")
        c.drawString(1*inch, y-0.8*inch, f"Date: {date.today().isoformat()}")
        c.showPage()
        c.save()


def wrap_text(text: str, max_width: float, pdf_mod) -> List[str]:
    """Very small word-wrap helper for ReportLab drawing."""
    if pdf_mod is None:
        return [text]
    # crude width estimator; ReportLab has stringWidth but keep deps minimal
    words = text.split()
    lines, cur = [], []
    def estw(s: str) -> float:
        # assume ~0.5% inch per char at 10pt Helvetica; rough but fine for templates
        return len(s) * 3.5
    curw = 0.0
    for w in words:
        ww = estw(w + ' ')
        if cur and curw + ww > max_width:
            lines.append(' '.join(cur))
            cur, curw = [w], ww
        else:
            cur.append(w)
            curw += ww
    if cur:
        lines.append(' '.join(cur))
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic invoices/contracts")
    ap.add_argument("--csv", type=Path, help="Output directory for CSV files")
    ap.add_argument("--json", type=Path, help="Output directory for per-invoice JSON files")
    ap.add_argument("--pdf", type=Path, help="Output directory for invoice PDFs")
    ap.add_argument("--contracts", type=Path, help="Output directory for contract PDFs")
    ap.add_argument("--n", type=int, default=12, help="Number of invoices to generate (base)")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    args = ap.parse_args()

    rng = Random(args.seed)
    fake = Faker()
    Faker.seed(args.seed)

    # Choose currencies with some distribution
    currency_choices = [cur for cur, _ in SUPPORTED_CURRENCIES]

    invoices: List[Invoice] = []
    vendor_count = len(VENDOR_POOL)

    # Generate base invoices
    for i in range(args.n):
        vendor_index = rng.randrange(vendor_count)
        vendor = VENDOR_POOL[vendor_index]
        currency = rng.choice(currency_choices)
        inv = build_invoice(rng, fake, vendor, vendor_index, i + 1, currency)
        invoices.append(inv)

        # Occasionally add a duplicate/correction
        if rng.random() < 0.15:
            invoices.append(maybe_duplicate_invoice(rng, inv))

    # Write outputs
    if args.csv:
        write_csv(args.csv, invoices)
        print(f"[ok] Wrote CSV to {args.csv}/invoices.csv and {args.csv}/invoice_lines.csv")

    if args.json:
        write_json(args.json, invoices)
        print(f"[ok] Wrote {len(invoices)} JSON files to {args.json}")

    if args.pdf:
        try:
            write_pdfs(args.pdf, invoices)
            print(f"[ok] Wrote {len(invoices)} invoice PDFs to {args.pdf}")
        except RuntimeError as e:
            print(f"[warn] {e}")

    if args.contracts:
        write_contract_pdfs(args.contracts, rng, n=3)
        print(f"[ok] Wrote contract templates to {args.contracts} (if reportlab installed)")

    if not any([args.csv, args.json, args.pdf, args.contracts]):
        print("No outputs selected. Use --csv/--json/--pdf/--contracts.")


if __name__ == "__main__":
    main()
