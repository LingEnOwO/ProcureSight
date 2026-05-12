#!/usr/bin/env python3
"""
Anomaly injection for ProcureSight dataset.

Reads invoices from dataset/generated/invoices_json/,
injects 50-100 anomalies, and writes a manifest to dataset/generated/anomalies.json.

Default (offline) mode uses random multipliers relative to the base invoice.

With --use-db, price_spike and quantity_spike are generated using real vendor/SKU
medians queried from the DB, guaranteeing the scoring thresholds are crossed.
Run --use-db only after upload_clean_invoices.py + ARQ worker have fully processed
all clean invoices.

Anomaly types:
  - duplicate_invoice_no_same_vendor : same invoice_no reused by the same vendor
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

import argparse
import copy
import json
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import psycopg
import psycopg.rows
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env.local")

from dataset.generators.utils import VENDOR_CATALOG, seed_all

JSON_DIR      = ROOT / "dataset/generated/invoices_json"
ANOMALIES_DIR = ROOT / "dataset/generated/anomalies"
ANOMALIES_OUT = ROOT / "dataset/generated/anomalies.json"
DB_URL        = os.getenv("DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight")

SEED        = 42
ANOMALY_MIN = 50
ANOMALY_MAX = 100

# DB-aware thresholds — must match values in anomaly_scoring.py
PRICE_MULTIPLIER = 3.5   # × median unit price → triggers "high" (threshold: 3×)
VOL_MULTIPLIER   = 2.5   # × median invoice total → triggers "medium" (threshold: 2×)
MIN_SAMPLE_SIZE  = 5     # MIN_SAMPLE_SIZE_FOR_BASELINE
MIN_INVOICES_VOL = 5     # MIN_INVOICES_FOR_SPEND_BASELINE

ANOMALY_WEIGHTS = {
    "price_spike":            20,
    "quantity_spike":         15,
    "tax_mismatch":           10,
    "vendor_name_variation":  10,
    "duplicate_invoice_no_same_vendor": 8,
    "duplicate_submission":    8,
    "out_of_cadence":          8,
    "negative_line_item":      8,
    "unusual_currency":        7,
    "excessive_consulting":    6,
}

DETECTABILITY = {
    "price_spike":           "current_rules",
    "quantity_spike":        "current_rules",
    "duplicate_invoice_no_same_vendor": "current_rules",
    "duplicate_submission":  "current_rules",
    "excessive_consulting":  "future_rag",
    "tax_mismatch":          "future_rag",
    "vendor_name_variation": "future_rag",
    "out_of_cadence":        "future_rag",
    "negative_line_item":    "future_rag",
    "unusual_currency":      "future_rag",
}


# ── DB helpers (used only in --use-db mode) ───────────────────────────────────

def _resolve_demo_org_id(db_url: str) -> str:
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM orgs WHERE name = 'Demo Org'")
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Demo Org not found — run `make seed` first")
        return str(row[0])


def _fetch_price_baselines(db_url: str, org_id: str) -> list[dict]:
    """Return vendor+SKU rows with sufficient price history."""
    with psycopg.connect(db_url) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (org_id,))
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT v.name AS vendor_name,
                       s.sku,
                       s."desc",
                       s.median_unit_price,
                       s.sample_size
                FROM vendor_unit_price_stats s
                JOIN vendors v ON v.id = s.vendor_id
                WHERE s.org_id = %(org_id)s
                  AND s.sample_size >= %(min)s
                  AND s.median_unit_price > 0
                  AND s.sku IS NOT NULL
                ORDER BY v.name, s.sku
                """,
                {"org_id": org_id, "min": MIN_SAMPLE_SIZE},
            )
            return cur.fetchall()


def _fetch_volume_baselines(db_url: str, org_id: str) -> list[dict]:
    """Return vendors with a stable invoice total median over 90d or 30d."""
    with psycopg.connect(db_url) as conn:
        conn.execute("SELECT set_config('app.org_id', %s, false)", (org_id,))
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT v.name AS vendor_name,
                       s.invoice_count_90d,
                       s.median_invoice_total_90d,
                       s.invoice_count_30d,
                       s.median_invoice_total_30d
                FROM vendor_spend_stats s
                JOIN vendors v ON v.id = s.vendor_id
                WHERE s.org_id = %(org_id)s
                  AND (
                    (s.invoice_count_90d >= %(min)s AND s.median_invoice_total_90d > 0)
                    OR
                    (s.invoice_count_30d >= %(min)s AND s.median_invoice_total_30d > 0)
                  )
                ORDER BY v.name
                """,
                {"org_id": org_id, "min": MIN_INVOICES_VOL},
            )
            return cur.fetchall()


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_invoices(directory: Path) -> dict[str, dict]:
    """Return {invoice_no: invoice_dict} from clean INV-*.json files only."""
    invoices: dict[str, dict] = {}
    for fp in sorted(directory.glob("INV-*.json")):
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

def inject_price_spike(
    inv: dict,
    rng: random.Random,
    sku: str | None = None,
    median_price: float | None = None,
) -> tuple[dict, dict]:
    result = copy.deepcopy(inv)

    if sku is not None and median_price is not None:
        # DB-aware: target the specific SKU line, set to PRICE_MULTIPLIER × actual median
        ln = next((l for l in result["lines"] if l.get("sku") == sku), None)
        if ln is None:
            raise ValueError(f"SKU {sku!r} not found in invoice {inv['invoice_no']}")
        new_price = round(median_price * PRICE_MULTIPLIER, 2)
        multiplier = PRICE_MULTIPLIER
        baseline_desc = f"median {median_price:.2f}"
    else:
        # Offline: random line, random multiplier of base invoice price
        ln = rng.choice(result["lines"])
        old_price = float(ln["unit_price"])
        multiplier = rng.uniform(3.0, 5.5)
        new_price = round(old_price * multiplier, 2)
        baseline_desc = f"baseline {old_price:.2f}"

    ln["unit_price"] = new_price
    ln["line_total"] = round(float(ln["qty"]) * new_price, 2)
    result["subtotal"] = round(sum(l["line_total"] for l in result["lines"]), 2)
    result["tax"] = round(result["subtotal"] * (inv["tax"] / inv["subtotal"] if inv["subtotal"] else 0), 2)
    result["total"] = round(result["subtotal"] + result["tax"], 2)

    return result, {
        "anomaly_type": "price_spike",
        "severity": "high",
        "explanation": (
            f"Line item '{ln['desc']}' has unit_price {new_price:.2f} "
            f"({multiplier:.1f}x the {baseline_desc}) — "
            f"far outside historical range for vendor {inv['vendor']}."
        ),
    }


def inject_quantity_spike(
    inv: dict,
    rng: random.Random,
    vendor_median_total: float | None = None,
) -> tuple[dict, dict]:
    result = copy.deepcopy(inv)
    tax_rate = inv["tax"] / inv["subtotal"] if inv["subtotal"] else 0

    if vendor_median_total is not None:
        # DB-aware: scale largest line's qty until invoice total > VOL_MULTIPLIER × vendor median
        target_total = vendor_median_total * VOL_MULTIPLIER
        current_total = float(inv["total"])
        ln = max(result["lines"], key=lambda l: float(l.get("line_total") or 0))
        old_qty = float(ln["qty"])
        unit_price = float(ln["unit_price"])
        if unit_price <= 0:
            raise ValueError("unit_price is zero — cannot scale quantity")
        additional_qty = (target_total - current_total) / unit_price
        ln["qty"] = round(old_qty + additional_qty, 2)
        multiplier = ln["qty"] / old_qty if old_qty else VOL_MULTIPLIER
    else:
        # Offline: random line, random multiplier of base qty
        ln = rng.choice(result["lines"])
        old_qty = float(ln["qty"])
        multiplier = rng.uniform(4.0, 6.0)
        ln["qty"] = round(old_qty * multiplier, 2)

    ln["line_total"] = round(float(ln["qty"]) * float(ln["unit_price"]), 2)
    result["subtotal"] = round(sum(l["line_total"] for l in result["lines"]), 2)
    result["tax"] = round(result["subtotal"] * tax_rate, 2)
    result["total"] = round(result["subtotal"] + result["tax"], 2)

    return result, {
        "anomaly_type": "quantity_spike",
        "severity": "medium",
        "explanation": (
            f"Line item '{ln['desc']}' has qty {ln['qty']} "
            f"({multiplier:.1f}x {'normal' if vendor_median_total else 'baseline'}) — "
            f"unusually large order volume for vendor {inv['vendor']}."
        ),
    }


def inject_tax_mismatch(inv: dict, rng: random.Random) -> tuple[dict, dict]:
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


def inject_vendor_name_variation(inv: dict, rng: random.Random, vmap: dict) -> tuple[dict, dict]:
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


def inject_duplicate_invoice_no(inv: dict, vendor_invoices: list[dict], rng: random.Random) -> tuple[dict, dict]:
    result = copy.deepcopy(inv)
    same_vendor_nos = [i["invoice_no"] for i in vendor_invoices if i["invoice_no"] != inv["invoice_no"]]
    if not same_vendor_nos:
        raise ValueError(f"No other invoices for vendor '{inv['vendor']}' to steal an invoice_no from")
    result["invoice_no"] = rng.choice(same_vendor_nos)
    orig_date = date.fromisoformat(inv["invoice_date"])
    result["invoice_date"] = (orig_date + timedelta(days=rng.randint(1, 5))).isoformat()
    return result, {
        "anomaly_type": "duplicate_invoice_no_same_vendor",
        "severity": "medium",
        "explanation": (
            f"Invoice number {result['invoice_no']} from {inv['vendor']} already exists in the system. "
            f"This duplicate was submitted {abs((date.fromisoformat(result['invoice_date']) - orig_date).days)} "
            f"days after the original, suggesting a duplicate payment attempt by the same vendor."
        ),
    }


def inject_duplicate_submission(inv: dict, rng: random.Random) -> tuple[dict, dict]:
    result = copy.deepcopy(inv)
    return result, {
        "anomaly_type": "duplicate_submission",
        "severity": "critical",
        "explanation": (
            f"Invoice {inv['invoice_no']} from {inv['vendor']} appears to be an exact "
            f"duplicate submission. Total: {inv['currency']} {inv['total']:.2f}. "
            f"Content fingerprint matches a previously processed invoice."
        ),
    }


def inject_out_of_cadence(inv: dict, rng: random.Random, vmap: dict) -> tuple[dict, dict]:
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


def inject_negative_line_item(inv: dict, rng: random.Random) -> tuple[dict, dict]:
    result = copy.deepcopy(inv)
    ln = rng.choice(result["lines"])
    ln["qty"]        = -abs(ln["qty"])
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


def inject_unusual_currency(inv: dict, rng: random.Random) -> tuple[dict, dict]:
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


def inject_excessive_consulting(inv: dict, rng: random.Random) -> tuple[dict, dict]:
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


# ── main ──────────────────────────────────────────────────────────────────────

def inject(
    json_dir: Path = JSON_DIR,
    output_dir: Path = ANOMALIES_DIR,
    output_path: Path = ANOMALIES_OUT,
    seed: int = SEED,
    verbose: bool = True,
    use_db: bool = False,
    db_url: str | None = None,
) -> list[dict]:
    seed_all(seed)
    rng = random.Random(seed + 99)

    invoices = _load_invoices(json_dir)
    if not invoices:
        print("  [warn] No invoices found — run generate_dataset.py first")
        return []

    by_vendor: dict[str, list[dict]] = {}
    for inv in invoices.values():
        by_vendor.setdefault(inv["vendor"], []).append(inv)

    vmap = _vendor_map()
    all_nos = set(invoices.keys())
    invoice_list = list(invoices.values())
    output_dir.mkdir(parents=True, exist_ok=True)

    consulting_invoices = [
        inv for inv in invoice_list
        if vmap.get(inv["vendor"]) and vmap[inv["vendor"]].category == "consulting"
    ]

    anomalies: list[dict] = []

    # ── DB-aware price_spike and quantity_spike ────────────────────────────────
    if use_db:
        actual_db_url = db_url or DB_URL
        org_id = _resolve_demo_org_id(actual_db_url)
        if verbose:
            print(f"  DB mode: org={org_id}")

        price_baselines = _fetch_price_baselines(actual_db_url, org_id)
        vol_baselines   = _fetch_volume_baselines(actual_db_url, org_id)
        if verbose:
            print(f"  Price baselines: {len(price_baselines)}  Vol baselines: {len(vol_baselines)}")

        for bl in price_baselines:
            vendor_invoices = by_vendor.get(bl["vendor_name"], [])
            candidates = [
                inv for inv in vendor_invoices
                if any(l.get("sku") == bl["sku"] for l in inv["lines"])
            ]
            if not candidates:
                continue
            base = rng.choice(candidates)
            try:
                modified, meta = inject_price_spike(
                    base, rng, sku=bl["sku"], median_price=float(bl["median_unit_price"])
                )
            except Exception as e:
                if verbose:
                    print(f"  [warn] price_spike skipped {bl['vendor_name']}/{bl['sku']}: {e}")
                continue
            modified["invoice_no"] = f"ANOM-{len(anomalies)+1:04d}-{base['invoice_no']}"
            modified["invoice_date"] = date.today().isoformat()
            modified["due_date"] = (date.today() + timedelta(days=30)).isoformat()
            _save_invoice(modified, output_dir)
            all_nos.add(modified["invoice_no"])
            anomalies.append({
                "invoice_no":    modified["invoice_no"],
                "anomaly_type":  "price_spike",
                "severity":      "high",
                "detectability": "current_rules",
                "explanation":   meta["explanation"],
            })

        for bl in vol_baselines:
            vendor_invoices = by_vendor.get(bl["vendor_name"], [])
            if not vendor_invoices:
                continue
            median_total = float(bl["median_invoice_total_90d"] or bl["median_invoice_total_30d"])
            base = rng.choice(vendor_invoices)
            try:
                modified, meta = inject_quantity_spike(base, rng, vendor_median_total=median_total)
            except Exception as e:
                if verbose:
                    print(f"  [warn] quantity_spike skipped {bl['vendor_name']}: {e}")
                continue
            modified["invoice_no"] = f"ANOM-{len(anomalies)+1:04d}-{base['invoice_no']}"
            modified["invoice_date"] = date.today().isoformat()
            modified["due_date"] = (date.today() + timedelta(days=30)).isoformat()
            _save_invoice(modified, output_dir)
            all_nos.add(modified["invoice_no"])
            anomalies.append({
                "invoice_no":    modified["invoice_no"],
                "anomaly_type":  "quantity_spike",
                "severity":      "medium",
                "detectability": "current_rules",
                "explanation":   meta["explanation"],
            })

    # ── Random anomalies (all types; skip price/quantity spike in DB mode) ─────
    types_pool = list(ANOMALY_WEIGHTS.keys())
    if use_db:
        types_pool = [t for t in types_pool if t not in ("price_spike", "quantity_spike")]
    weights_pool = [ANOMALY_WEIGHTS[t] for t in types_pool]

    anomaly_count = rng.randint(ANOMALY_MIN, ANOMALY_MAX)

    for _ in range(anomaly_count):
        anomaly_type = rng.choices(types_pool, weights=weights_pool, k=1)[0]

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
            elif anomaly_type == "duplicate_invoice_no_same_vendor":
                modified, meta = inject_duplicate_invoice_no(base, by_vendor.get(base["vendor"], []), rng)
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

        if anomaly_type not in ("duplicate_invoice_no_same_vendor", "duplicate_submission"):
            modified["invoice_no"] = f"ANOM-{len(anomalies)+1:04d}-{modified['invoice_no']}"

        _save_invoice(modified, output_dir)
        all_nos.add(modified["invoice_no"])
        anomalies.append({
            "invoice_no":    modified["invoice_no"],
            "anomaly_type":  meta["anomaly_type"],
            "severity":      meta["severity"],
            "detectability": DETECTABILITY.get(meta["anomaly_type"], "future_rag"),
            "explanation":   meta["explanation"],
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(anomalies, indent=2), encoding="utf-8")

    if verbose:
        by_type: dict[str, int] = {}
        for a in anomalies:
            by_type[a["anomaly_type"]] = by_type.get(a["anomaly_type"], 0) + 1
        print(f"  Injected {len(anomalies)} anomalies:")
        for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
            det = DETECTABILITY.get(t, "future_rag")
            print(f"    {t:<30s} {n:>3d}  [{det}]")
        print(f"  Anomaly files → {output_dir}")
        print(f"  Manifest      → {output_path}")

    return anomalies


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject anomalies into the ProcureSight dataset")
    parser.add_argument("--json-dir",   type=Path, default=JSON_DIR,      help="Clean invoice source directory")
    parser.add_argument("--output-dir", type=Path, default=ANOMALIES_DIR, help="Output directory for ANOM-*.json files")
    parser.add_argument("--manifest",   type=Path, default=ANOMALIES_OUT, help="Manifest JSON output path")
    parser.add_argument("--seed",       type=int,  default=SEED)
    parser.add_argument(
        "--use-db",
        action="store_true",
        help="Use real DB medians for price_spike and quantity_spike (run after upload_clean_invoices.py)",
    )
    parser.add_argument("--db-url", default=None, help="Database URL (default: $DATABASE_URL)")
    args = parser.parse_args()

    print("Injecting anomalies...")
    anomalies = inject(
        json_dir=args.json_dir,
        output_dir=args.output_dir,
        output_path=args.manifest,
        seed=args.seed,
        verbose=True,
        use_db=args.use_db,
        db_url=args.db_url,
    )
    print(f"Done. Total anomalies: {len(anomalies)}")
