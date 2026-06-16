#!/usr/bin/env python3
"""
Master script: runs the full ProcureSight dataset generation pipeline.

Steps:
  1. Generate JSON, CSV, and PDF invoices
  2. Inject anomalies
  3. Generate contracts and policies

Usage:
    cd /path/to/ProcureSight
    source venv/bin/activate
    python dataset/generators/run_all.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dataset.generators import generate_dataset, inject_anomalies, generate_contracts


def main() -> None:
    t0 = time.time()
    print("=" * 60)
    print("  ProcureSight Dataset Generator")
    print("=" * 60)

    print("\n[1/3] Generating invoices...")
    invoices = generate_dataset.generate(verbose=True)
    print(f"      → {len(invoices)} invoices generated")

    print("\n[2/3] Injecting anomalies...")
    anomalies = inject_anomalies.inject(verbose=True)
    print(f"      → {len(anomalies)} anomalies injected")

    print("\n[3/3] Generating contracts and policies...")
    generate_contracts.generate(verbose=True)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  Done in {elapsed:.1f}s")
    print(f"  Invoices : {len(invoices)}")
    print(f"  Anomalies: {len(anomalies)}")
    print(f"  Output   : dataset/generated/")
    print("=" * 60)


if __name__ == "__main__":
    main()
