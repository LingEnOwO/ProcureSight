#!/usr/bin/env python3
"""
Anomaly injection for ProcureSight dataset.

Reads invoices from dataset/generated/invoices_json/,
injects 50-100 anomalies (modifying files in-place),
and writes a manifest to dataset/generated/anomalies.json.

Anomaly types:
  - duplicate_invoice_no      : same invoice_no as an existing invoice
  - price_spike               : unit_price 3-5x the vendor baseline
  - quantity_spike            : qty 4-6x normal
  - tax_mismatch              : tax does not match expected rate
  - vendor_name_variation     : known vendor with alternate spelling
  - duplicate_submission      : identical invoice submitted twice
  - out_of_cadence            : invoice date far outside normal window
  - negative_line_item        : one line has negative qty/price
  - unusual_currency          : USD vendor billed in JPY or EUR
  - excessive_consulting      : consulting invoice with unusually high total
"""
from __future__ import annotations

import copy
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dataset.generators.utils import VENDOR_CATALOG, seed_all

JSON_DIR      = ROOT / "dataset/generated/invoices_json"
ANOMALIES_OUT = ROOT / "dataset/generated/anomalies.json"

SEED            = 42
ANOMALY_MIN     = 50
ANOMALY_MAX     = 100

ANOMALY_WEIGHTS = {
    "price_spike":            20,
    "quantity_spike":         15,
    "tax_mismatch":           10,
    "vendor_name_variation":  10,
    "duplicate_invoice_no":    8,
    "duplicate_submission":    8,
    "out_of_cadence":          8,
    "negative_line_item":      8,
    "unusual_currency":        7,
    "excessive_consulting":    6,
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_invoices(directory: Path) -> dict[str, dict]:
    """Return {invoice_no: invoice_dict} from JSON files."""
    invoices: dict[str, dict] = {}
    for fp in sorted(directory.glob("*.json")):
        try:
            inv = json.loads(fp.read_text(encoding="utf-8"))
            invoices[inv["invoice_no"]] = inv
        except Exception:
            pass
    return invoices


def _save_invoice(inv: dict, directory: Path) -> None:
    safe = inv["invoice_no"].replace("/", "_").replace(" ", "_")
    path = directory / f"{safe}.json"
    path.write_text(json.dumps(inv, indent=2), encoding="utf-8")


def _vendor_map() -> dict[str, Any]:
    return {v.name: v for v in VENDOR_CATALOG}


# ── individual anomaly injectors ──────────────────────────────────────────────

def inject_price_spike(inv: dict, rng: random.Random) -> dict:
    result = copy.deepcopy(inv)
    ln = rng.choice(result["lines"])
    multiplier = rng.uniform(3.0, 5.5)
    old_price = ln["unit_price"]
    ln["unit_price"] = round(old_price * multiplier, 2)
    ln["line_total"]  = round(ln["qty"] * ln["unit_price"], 2)
    result["subtotal"] = round(sum(l["line_total"] for l in result["lines"]), 2)
    result["tax"]      = round(result["subtotal"] * (result["tax"] / inv["subtotal"] if inv["subtotal"] else 0), 2)
    result["total"]    = round(result["subtotal"] + result["tax"], 2)
    return result, {
        "anomaly_type": "price_spike",
        "severity": "high",
        "explanation": (
            f"Line item '{ln['desc']}' has unit_price {ln['unit_price']:.2f} "
            f"({multiplier:.1f}x the baseline of {old_price:.2f}) — "
            f"far outside historical range for vendor {inv['vendor']}."
        ),
    }


def inject_quantity_spike(inv: dict, rng: random.Random) -> dict:
    result = copy.deepcopy(inv)
    ln = rng.choice(result["lines"])
    multiplier = rng.uniform(4.0, 6.0)
    old_qty = ln["qty"]
    ln["qty"]       = round(old_qty * multiplier, 2)
    ln["line_total"] = round(ln["qty"] * ln["unit_price"], 2)
    result["subtotal"] = round(sum(l["line_total"] for l in result["lines"]), 2)
    result["total"]    = round(result["subtotal"] + result["tax"], 2)
    return result, {
        "anomaly_type": "quantity_spike",
        "severity": "medium",
        "explanation": (
            f"Line item '{ln['desc']}' has qty {ln['qty']} "
            f"({multiplier:.1f}x the baseline of {old_qty}) — "
            f"unusually large order volume for vendor {inv['vendor']}."
        ),
    }


def inject_tax_mismatch(inv: dict, rng: random.Random) -> dict:
    result = copy.deepcopy(inv)
    bad_rate = rng.choice([0.15, 0.20, 0.25, 0.03, 0.00])
    result["tax"]   = round(result["subtotal"] * bad_rate, 2)
    result["total"] = round(result["subtotal"] + result["tax"], 2)
    expected = round(result["subtotal"] * (inv["tax"] / inv["subtotal"] if inv["subtotal"] else 0), 2)
    return result, {
        "anomaly_type": "tax_mismatch",
        "severity": "medium",
        "explanation": (
            f"Tax of {result['tax']:.2f} ({bad_rate*100:.0f}%) does not match "
            f"expected tax of {expected:.2f} based on vendor's historical rate. "
            f"Possible billing error or incorrect tax jurisdiction applied."
        ),
    }


def inject_vendor_name_variation(inv: dict, rng: random.Random, vmap: dict) -> dict:
    result = copy.deepcopy(inv)
    vendor = vmap.get(inv["vendor"])
    if not vendor or not vendor.alternate_names:
        result["vendor"] = inv["vendor"].upper()
        alt = result["vendor"]
    else:
        alt = rng.choice(vendor.alternate_names)
        result["vendor"] = alt
    return result, {
        "anomaly_type": "vendor_name_variation",
        "severity": "low",
        "explanation": (
            f"Vendor name '{alt}' is a variation of the canonical "
            f"'{inv['vendor']}'. May cause duplicate vendor records or "
            f"failed contract matching in downstream systems."
        ),
    }


def inject_duplicate_invoice_no(inv: dict, existing_nos: set, rng: random.Random) -> dict:
    result = copy.deepcopy(inv)
    # Pick an existing invoice_no (not itself)
    candidates = list(existing_nos - {inv["invoice_no"]})
    if candidates:
        result["invoice_no"] = rng.choice(candidates)
    else:
        result["invoice_no"] = inv["invoice_no"]   # self-duplicate
    # Slightly alter date to make it look like a re-submission
    orig_date = date.fromisoformat(inv["invoice_date"])
    result["invoice_date"] = (orig_date + timedelta(days=rng.randint(1, 5))).isoformat()
    return result, {
        "anomaly_type": "duplicate_invoice_no",
        "severity": "medium",
        "explanation": (
            f"Invoice number {result['invoice_no']} already exists in the system. "
            f"This duplicate was submitted {abs((date.fromisoformat(result['invoice_date']) - orig_date).days)} "
            f"days after the original, suggesting a duplicate payment attempt."
        ),
    }


def inject_duplicate_submission(inv: dict, rng: random.Random) -> dict:
    result = copy.deepcopy(inv)
    # Identical content but different submission date — same invoice_no
    return result, {
        "anomaly_type": "duplicate_submission",
        "severity": "critical",
        "explanation": (
            f"Invoice {inv['invoice_no']} from {inv['vendor']} appears to be an exact "
            f"duplicate submission. Total: {inv['currency']} {inv['total']:.2f}. "
            f"Content fingerprint matches a previously processed invoice."
        ),
    }


def inject_out_of_cadence(inv: dict, rng: random.Random, vmap: dict) -> dict:
    result = copy.deepcopy(inv)
    vendor = vmap.get(inv["vendor"])
    cadence_days = {"monthly": 30, "bimonthly": 60, "quarterly": 91, "asneeded": 30}.get(
        vendor.invoice_cadence if vendor else "monthly", 30
    )
    shift = rng.choice([-1, 1]) * rng.randint(cadence_days * 2, cadence_days * 4)
    orig = date.fromisoformat(inv["invoice_date"])
    new_date = orig + timedelta(days=shift)
    result["invoice_date"] = new_date.isoformat()
    if result["due_date"]:
        due = date.fromisoformat(result["due_date"])
        result["due_date"] = (due + timedelta(days=shift)).isoformat()
    return result, {
        "anomaly_type": "out_of_cadence",
        "severity": "medium",
        "explanation": (
            f"Invoice dated {result['invoice_date']} is {abs(shift)} days "
            f"outside the expected {vendor.invoice_cadence if vendor else 'regular'} "
            f"cadence for vendor {inv['vendor']}. Could indicate catch-up billing or fraud."
        ),
    }


def inject_negative_line_item(inv: dict, rng: random.Random) -> dict:
    result = copy.deepcopy(inv)
    ln = rng.choice(result["lines"])
    ln["qty"]       = -abs(ln["qty"])
    ln["line_total"] = round(ln["qty"] * ln["unit_price"], 2)
    result["subtotal"] = round(sum(l["line_total"] for l in result["lines"]), 2)
    result["tax"]      = round(max(result["subtotal"], 0) * (inv["tax"] / inv["subtotal"] if inv["subtotal"] else 0), 2)
    result["total"]    = round(result["subtotal"] + result["tax"], 2)
    return result, {
        "anomaly_type": "negative_line_item",
        "severity": "medium",
        "explanation": (
            f"Line item '{ln['desc']}' has a negative quantity ({ln['qty']}), "
            f"resulting in a negative line total of {ln['line_total']:.2f}. "
            f"May represent an unauthorized credit or data entry error."
        ),
    }


def inject_unusual_currency(inv: dict, rng: random.Random) -> dict:
    result = copy.deepcopy(inv)
    alt_currencies = [c for c in ["USD", "EUR", "JPY"] if c != inv["currency"]]
    new_currency = rng.choice(alt_currencies)
    result["currency"] = new_currency
    return result, {
        "anomaly_type": "unusual_currency",
        "severity": "medium",
        "explanation": (
            f"Invoice from {inv['vendor']} is denominated in {new_currency} "
            f"but this vendor historically invoices in {inv['currency']}. "
            f"Possible contract violation or unauthorized currency change."
        ),
    }


def inject_excessive_consulting(inv: dict, rng: random.Random) -> dict:
    result = copy.deepcopy(inv)
    multiplier = rng.uniform(3.0, 6.0)
    for ln in result["lines"]:
        ln["unit_price"] = round(ln["unit_price"] * multiplier, 2)
        ln["line_total"]  = round(ln["qty"] * ln["unit_price"], 2)
    result["subtotal"] = round(sum(l["line_total"] for l in result["lines"]), 2)
    result["tax"]      = round(result["subtotal"] * (inv["tax"] / inv["subtotal"] if inv["subtotal"] else 0), 2)
    result["total"]    = round(result["subtotal"] + result["tax"], 2)
    return result, {
        "anomaly_type": "excessive_consulting",
        "severity": "high",
        "explanation": (
            f"Consulting invoice from {inv['vendor']} totals "
            f"{result['currency']} {result['total']:.2f} — approximately "
            f"{multiplier:.1f}x the typical monthly spend for this vendor. "
            f"Requires senior approval per procurement policy."
        ),
    }


# ── main ─────────────────────────────────────────────────────────────────────

def inject(
    json_dir: Path = JSON_DIR,
    output_path: Path = ANOMALIES_OUT,
    seed: int = SEED,
    verbose: bool = True,
) -> list[dict]:
    seed_all(seed)
    rng = random.Random(seed + 99)   # offset so anomaly RNG differs from generation RNG

    invoices = _load_invoices(json_dir)
    if not invoices:
        print("  [warn] No invoices found — run generate_dataset.py first")
        return []

    vmap = _vendor_map()
    all_nos = set(invoices.keys())
    invoice_list = list(invoices.values())

    # filter by category for consulting anomalies
    consulting_invoices = [
        inv for inv in invoice_list
        if vmap.get(inv["vendor"]) and vmap[inv["vendor"]].category == "consulting"
    ]

    anomaly_count = rng.randint(ANOMALY_MIN, ANOMALY_MAX)
    types = list(ANOMALY_WEIGHTS.keys())
    weights = [ANOMALY_WEIGHTS[t] for t in types]

    anomalies: list[dict] = []
    injected_nos: set[str] = set()

    for _ in range(anomaly_count):
        anomaly_type = rng.choices(types, weights=weights, k=1)[0]

        # pick a suitable base invoice
        if anomaly_type == "excessive_consulting" and consulting_invoices:
            base = rng.choice(consulting_invoices)
        else:
            base = rng.choice(invoice_list)

        try:
            if anomaly_type == "price_spike":
                modified, meta = inject_price_spike(base, rng)
            elif anomaly_type == "quantity_spike":
                modified, meta = inject_quantity_spike(base, rng)
            elif anomaly_type == "tax_mismatch":
                modified, meta = inject_tax_mismatch(base, rng)
            elif anomaly_type == "vendor_name_variation":
                modified, meta = inject_vendor_name_variation(base, rng, vmap)
            elif anomaly_type == "duplicate_invoice_no":
                modified, meta = inject_duplicate_invoice_no(base, all_nos, rng)
            elif anomaly_type == "duplicate_submission":
                modified, meta = inject_duplicate_submission(base, rng)
            elif anomaly_type == "out_of_cadence":
                modified, meta = inject_out_of_cadence(base, rng, vmap)
            elif anomaly_type == "negative_line_item":
                modified, meta = inject_negative_line_item(base, rng)
            elif anomaly_type == "unusual_currency":
                modified, meta = inject_unusual_currency(base, rng)
            elif anomaly_type == "excessive_consulting":
                modified, meta = inject_excessive_consulting(base, rng)
            else:
                continue
        except Exception as e:
            if verbose:
                print(f"  [warn] {anomaly_type} injection failed on {base['invoice_no']}: {e}")
            continue

        # Generate a new invoice_no for non-duplicate anomalies to avoid conflicts
        if anomaly_type not in ("duplicate_invoice_no", "duplicate_submission"):
            modified["invoice_no"] = f"ANOM-{len(anomalies)+1:04d}-{modified['invoice_no']}"

        _save_invoice(modified, json_dir)
        all_nos.add(modified["invoice_no"])
        injected_nos.add(modified["invoice_no"])

        anomalies.append({
            "invoice_no":   modified["invoice_no"],
            "anomaly_type": meta["anomaly_type"],
            "severity":     meta["severity"],
            "explanation":  meta["explanation"],
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(anomalies, indent=2), encoding="utf-8")

    if verbose:
        by_type: dict[str, int] = {}
        for a in anomalies:
            by_type[a["anomaly_type"]] = by_type.get(a["anomaly_type"], 0) + 1
        print(f"  Injected {len(anomalies)} anomalies:")
        for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"    {t:<30s} {n}")
        print(f"  Anomaly manifest → {output_path}")

    return anomalies


if __name__ == "__main__":
    print("Injecting anomalies...")
    anomalies = inject(verbose=True)
    print(f"Done. Total anomalies: {len(anomalies)}")
