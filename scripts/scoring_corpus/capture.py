"""Capture the golden corpus: what the scorer produces today, for every invoice.

Run this *before* any scoring code moves. Captured afterwards it records the new
behaviour and proves nothing.

    source venv/bin/activate
    python -m scripts.scoring_corpus.capture

What it does, per invoice: run the real ``score_invoice`` against Postgres with
every repository read recorded, rewrite the database's UUIDs to values derived
from the dataset's own names, then replay the recording through the scorer and
require the same alerts back. That last step is what makes the recording
trustworthy — a read the tape missed would replay differently, or not at all.

Clean invoices are already in the database and are only read. Anomaly invoices
are not, so each one is inserted, scored and deleted again, one at a time: that
scores it against the clean history exactly as the injection run would, and
leaves the database as it was found. The 28 anomalies that duplicate an existing
invoice never reach the scorer in production — they are rejected pre-insert —
so their entry records the pre-insert duplicate check instead.

``excessive_consulting`` calls the embedding API, so OPENAI_API_KEY must be set;
without it the rule silently retrieves nothing and the corpus would pin an
emptiness that is an artefact of the capture run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

import psycopg

from apps.api.models.invoice import Invoice
from apps.api.repos.invoices import ensure_vendor, find_invoice_by_key
from apps.api.services.anomaly_scoring import build_duplicate_alert, score_invoice
from apps.api.services.invoice_persistence import persist_invoice
from apps.api.services.structured_extract import parse_json_bytes
from apps.api.services.validator import validate_invoice
from apps.api.settings import settings

from scripts.scoring_corpus.tape import (
    CAPTURE_RAW_DOC_ID,
    DUPLICATE_CHECK,
    REJECTED_BY_VALIDATION,
    SCORED,
    DuplicateCheckTape,
    ScoringTape,
    intercepting,
    alert_to_json,
    chunk_fingerprint,
    expected_from_dataset,
    replay_entry_async,
    seam_function,
    stats_key,
    summarize,
    synthetic_id,
    write_corpus,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CLEAN_DIR = REPO_ROOT / "dataset" / "generated" / "invoices_json"
ANOMALY_DIR = REPO_ROOT / "dataset" / "generated" / "anomalies"
MANIFEST = REPO_ROOT / "dataset" / "generated" / "anomalies.json"
DEFAULT_OUT = REPO_ROOT / "dataset" / "golden" / "scoring"


# ── Recording ────────────────────────────────────────────────────────────────

@contextmanager
def recording(tape: ScoringTape) -> Iterator[None]:
    """Run the scorer for real, writing every repository read into ``tape``."""
    real_fetch_lines = seam_function("_fetch_invoice_lines")
    real_contract = seam_function("get_vendor_contract")
    real_search = seam_function("_search_chunks_async")
    real_price_stats = seam_function("get_vendor_unit_price_stats")
    real_spend_stats = seam_function("get_vendor_spend_stats")

    async def fetch_invoice_lines(db, *, org_id, invoice_id):
        rows = await real_fetch_lines(db, org_id=org_id, invoice_id=invoice_id)
        # All four rules issue this same query; recording the first is enough.
        if not tape.invoice_rows:
            tape.invoice_rows = [dict(r) for r in rows]
        return rows

    async def unit_price_stats(db, *, org_id, vendor_id=None, sku=None, desc=None):
        rows = await real_price_stats(db, org_id=org_id, vendor_id=vendor_id, sku=sku, desc=desc)
        tape.unit_price_stats[stats_key(str(vendor_id), sku, desc)] = [dict(r) for r in rows]
        return rows

    async def spend_stats(db, *, org_id, vendor_id=None):
        rows = await real_spend_stats(db, org_id=org_id, vendor_id=vendor_id)
        tape.spend_stats[str(vendor_id)] = [dict(r) for r in rows]
        return rows

    async def vendor_contract(db, *, org_id, vendor_id):
        row = await real_contract(db, org_id=org_id, vendor_id=vendor_id)
        tape.contracts[str(vendor_id)] = dict(row) if row is not None else None
        return row

    async def search_chunks(db, org_id, query, source_types=None, limit=5):
        chunks = await real_search(db, org_id, query, source_types=source_types, limit=limit)
        tape.retrieval = {
            "query": query,
            "source_types": source_types,
            "limit": limit,
            "chunks": [dict(c) for c in chunks],
        }
        return chunks

    with intercepting(
        _fetch_invoice_lines=fetch_invoice_lines,
        get_vendor_contract=vendor_contract,
        _search_chunks_async=search_chunks,
        get_vendor_unit_price_stats=unit_price_stats,
        get_vendor_spend_stats=spend_stats,
    ):
        yield


async def record_sku_baselines(aconn: Any, tape: ScoringTape, *, org_id: str) -> None:
    """Also record the price baselines keyed by (vendor, sku) alone.

    Today's rule looks one up per line, filtering on the line description as well
    as the SKU. #15 replaces that with one batched fetch keyed by the invoice's
    SKUs — a call this tape would otherwise have no answer for, so replaying the
    refactor would raise instead of comparing. Per ADR-0001 the description
    carries no identity, so these are the un-narrowed rows for the same keys, and
    recording them now is what keeps the corpus usable *after* the code moves.
    Nothing reads them today.
    """
    read_stats = seam_function("get_vendor_unit_price_stats")
    keys = {
        (str(row["vendor_id"]), row["sku"])
        for row in tape.invoice_rows
        if row["sku"] is not None
    }
    for vendor_id, sku in sorted(keys):
        key = stats_key(vendor_id, sku, None)
        if key in tape.unit_price_stats:
            continue
        rows = await read_stats(aconn, org_id=org_id, vendor_id=vendor_id, sku=sku)
        tape.unit_price_stats[key] = [dict(row) for row in rows]


# ── Identifier rewriting ─────────────────────────────────────────────────────

def canonicalize(value: Any, id_map: Dict[str, str]) -> Any:
    """Replace this database's identifiers with dataset-derived ones, everywhere.

    Ids reach the corpus three ways — as row values, as lookup keys, and spelled
    out inside message strings — so the substitution is textual and applies to
    dict keys as well as values.
    """
    if isinstance(value, str):
        for real, synthetic in id_map.items():
            if real in value:
                value = value.replace(real, synthetic)
        return value
    if isinstance(value, dict):
        return {canonicalize(k, id_map): canonicalize(v, id_map) for k, v in value.items()}
    if isinstance(value, list):
        return [canonicalize(v, id_map) for v in value]
    return value


def id_map_for(
    *,
    org_id: str,
    org_name: str,
    invoice_no: str,
    vendor_names: Dict[str, str],
    tape: Optional[ScoringTape] = None,
    extra_invoices: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    id_map = {str(org_id): synthetic_id("org", org_name)}

    for vendor_id, vendor_name in vendor_names.items():
        id_map[str(vendor_id)] = synthetic_id("vendor", vendor_name)

    for real_invoice_id, real_invoice_no in (extra_invoices or {}).items():
        id_map[str(real_invoice_id)] = synthetic_id("invoice", real_invoice_no)

    if tape is not None:
        id_map[str(tape.invoice_id)] = synthetic_id("invoice", invoice_no)
        for index, row in enumerate(tape.invoice_rows):
            id_map[str(row["line_id"])] = synthetic_id("line", invoice_no, str(index))
        if tape.retrieval:
            for chunk in tape.retrieval["chunks"]:
                id_map[str(chunk["id"])] = synthetic_id(
                    "chunk", chunk_fingerprint(chunk["chunk_text"])
                )

    return id_map


# ── Entries ──────────────────────────────────────────────────────────────────

def _entry(
    *,
    invoice_key: str,
    kind: str,
    source: str,
    anomaly_type: Optional[str],
    detectability: Optional[str],
    inputs: Dict[str, Any],
    alerts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "invoice_key": invoice_key,
        "kind": kind,
        "source": source,
        "anomaly_type": anomaly_type,
        "detectability": detectability,
        "inputs": inputs,
        "alerts": alerts,
    }


async def _verify_replays(entry: Dict[str, Any]) -> None:
    """Round-trip the entry through disk-shaped JSON and re-score it."""
    reloaded = json.loads(json.dumps(entry, ensure_ascii=False, sort_keys=True))
    replayed = [alert_to_json(a) for a in await replay_entry_async(reloaded)]
    if replayed != reloaded["alerts"]:
        raise AssertionError(
            f"capture for {entry['invoice_key']} does not replay:\n"
            f"  live    : {json.dumps(reloaded['alerts'], sort_keys=True)[:600]}\n"
            f"  replayed: {json.dumps(replayed, sort_keys=True)[:600]}"
        )


async def capture_scored_invoice(
    aconn: psycopg.AsyncConnection,
    *,
    org_id: str,
    org_name: str,
    invoice_id: str,
    invoice_no: str,
    vendor_names: Dict[str, str],
    source: str,
    anomaly_type: Optional[str],
    detectability: Optional[str],
) -> Dict[str, Any]:
    tape = ScoringTape(org_id=str(org_id), invoice_id=str(invoice_id))
    with recording(tape):
        alerts = await score_invoice(aconn, org_id=str(org_id), invoice_id=str(invoice_id))

    await record_sku_baselines(aconn, tape, org_id=str(org_id))

    id_map = id_map_for(
        org_id=org_id,
        org_name=org_name,
        invoice_no=invoice_no,
        vendor_names=vendor_names,
        tape=tape,
    )
    entry = _entry(
        invoice_key=invoice_no,
        kind=SCORED,
        source=source,
        anomaly_type=anomaly_type,
        detectability=detectability,
        inputs=canonicalize(tape.to_json(), id_map),
        alerts=canonicalize([alert_to_json(a) for a in alerts], id_map),
    )
    await _verify_replays(entry)
    return entry


async def capture_duplicate_check(
    *,
    org_id: str,
    org_name: str,
    vendor_id: str,
    vendor_names: Dict[str, str],
    existing: Dict[str, Any],
    invoice: Invoice,
    anomaly_type: str,
    detectability: str,
) -> Dict[str, Any]:
    # raw_doc ids are assigned per upload and differ on every dataset load, so
    # they are pinned rather than recorded.
    existing_row = dict(existing)
    existing_row["raw_doc_id"] = CAPTURE_RAW_DOC_ID

    tape = DuplicateCheckTape(
        org_id=str(org_id),
        vendor_id=str(vendor_id),
        existing=existing_row,
        incoming_invoice_no=invoice.invoice_no,
        incoming_vendor=invoice.vendor,
        incoming_total=float(invoice.total),
    )
    alert = build_duplicate_alert(
        org_id=str(org_id),
        vendor_id=str(vendor_id),
        existing=existing_row,
        incoming_invoice_no=invoice.invoice_no,
        incoming_vendor=invoice.vendor,
        incoming_total=float(invoice.total),
        incoming_raw_doc_id=CAPTURE_RAW_DOC_ID,
    )

    id_map = id_map_for(
        org_id=org_id,
        org_name=org_name,
        invoice_no=invoice.invoice_no,
        vendor_names=vendor_names,
        extra_invoices={str(existing["id"]): invoice.invoice_no},
    )
    entry = _entry(
        invoice_key=invoice.invoice_no,
        kind=DUPLICATE_CHECK,
        source="anomaly",
        anomaly_type=anomaly_type,
        detectability=detectability,
        inputs=canonicalize(tape.to_json(), id_map),
        alerts=canonicalize([alert_to_json(alert)], id_map),
    )
    await _verify_replays(entry)
    return entry


# ── Database plumbing ────────────────────────────────────────────────────────

def resolve_org(conn: psycopg.Connection, org_name: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM orgs WHERE name = %s", (org_name,))
        row = cur.fetchone()
    if not row:
        sys.exit(f"[error] org {org_name!r} not found — run `make seed` first")
    return str(row[0])


def vendor_names_for(conn: psycopg.Connection, org_id: str) -> Dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, false)", (org_id,))
        cur.execute("SELECT id, name FROM vendors WHERE org_id = %s", (org_id,))
        return {str(vid): name for vid, name in cur.fetchall()}


def clean_invoices(conn: psycopg.Connection, org_id: str) -> List[Tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, invoice_no FROM invoices WHERE org_id = %s ORDER BY invoice_no",
            (org_id,),
        )
        return [(str(iid), no) for iid, no in cur.fetchall()]


def load_invoice(path: pathlib.Path) -> Tuple[Optional[Invoice], List[Dict[str, Any]]]:
    """Parse and validate one dataset file the way the worker does."""
    doc = parse_json_bytes(path.read_bytes())
    invoice = Invoice(**doc)
    report = validate_invoice(invoice)
    if report.has_errors:
        return None, [e.dict() for e in report.errors]
    return report.normalized_invoice, []


def insert_invoice_for_scoring(
    conn: psycopg.Connection, *, org_id: str, invoice: Invoice
) -> Tuple[Optional[str], Optional[Dict[str, Any]], str, bool]:
    """Insert an anomaly invoice so it can be scored.

    Returns (invoice_id, existing_row, vendor_id, vendor_was_created). When
    ``existing_row`` is set the invoice was not inserted: production rejects it
    pre-insert as a duplicate.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, false)", (org_id,))
        cur.execute(
            "SELECT id FROM vendors WHERE org_id = %s AND name = %s", (org_id, invoice.vendor)
        )
        vendor_was_created = cur.fetchone() is None

    vendor_id = str(ensure_vendor(conn, org_id, invoice.vendor))
    existing = find_invoice_by_key(conn, org_id, vendor_id, invoice.invoice_no)
    if existing:
        conn.rollback()
        return None, dict(existing), vendor_id, vendor_was_created

    invoice_id = persist_invoice(
        conn,
        org_id=org_id,
        vendor_id=vendor_id,
        invoice=invoice,
        raw_doc_id=None,
        upsert=False,
    )
    conn.commit()
    return str(invoice_id), None, vendor_id, vendor_was_created


def remove_captured_invoice(
    conn: psycopg.Connection,
    *,
    org_id: str,
    invoice_id: Optional[str],
    vendor_id: Optional[str],
    vendor_was_created: bool,
) -> None:
    """Undo an insert made only so the scorer had something to read.

    Runs on the maintenance connection: the application role has INSERT and
    SELECT policies on ``invoices`` but no DELETE policy, so a delete there
    removes nothing and reports no error. Row counts are checked for the same
    reason — a cleanup that quietly does nothing leaves the next capture run
    scoring against a polluted history.
    """
    with conn.cursor() as cur:
        if invoice_id:
            cur.execute("DELETE FROM invoices WHERE org_id = %s AND id = %s", (org_id, invoice_id))
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"failed to remove captured invoice {invoice_id} "
                    f"(deleted {cur.rowcount} rows) — the database is now polluted"
                )
        if vendor_was_created and vendor_id:
            cur.execute("DELETE FROM vendors WHERE org_id = %s AND id = %s", (org_id, vendor_id))
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"failed to remove captured vendor {vendor_id} (deleted {cur.rowcount} rows)"
                )
    conn.commit()


# ── Run ──────────────────────────────────────────────────────────────────────

async def run(
    org_name: str, out_dir: pathlib.Path, limit: Optional[int], maintenance_url: str
) -> None:
    if not settings.openai_api_key:
        sys.exit(
            "[error] OPENAI_API_KEY is not set. excessive_consulting retrieves nothing "
            "without it, and the corpus would pin that emptiness as if it were behaviour."
        )

    manifest = json.loads(MANIFEST.read_text())
    manifest_by_no = {entry["invoice_no"]: entry for entry in manifest}
    dataset_clean = {p.stem for p in CLEAN_DIR.glob("INV-*.json")}

    conn = psycopg.connect(settings.DATABASE_APP_URL)
    aconn = await psycopg.AsyncConnection.connect(settings.DATABASE_APP_URL)
    maint = psycopg.connect(maintenance_url)
    entries: List[Dict[str, Any]] = []
    started = time.time()

    try:
        org_id = resolve_org(conn, org_name)
        await aconn.execute("SELECT set_config('app.org_id', %s, false)", (org_id,))
        vendor_names = vendor_names_for(conn, org_id)

        loaded = clean_invoices(conn, org_id)
        loaded_nos = {no for _, no in loaded}
        if loaded_nos != dataset_clean:
            sys.exit(
                f"[error] database holds {len(loaded_nos)} invoices for {org_name!r} but the "
                f"dataset has {len(dataset_clean)} clean invoices "
                f"({len(dataset_clean - loaded_nos)} missing, "
                f"{len(loaded_nos - dataset_clean)} unexpected). Load the clean invoices "
                "first — see dataset/golden/README.md."
            )

        clean = loaded[:limit] if limit else loaded
        print(f"Clean invoices : {len(clean)}")

        for index, (invoice_id, invoice_no) in enumerate(clean, start=1):
            entries.append(
                await capture_scored_invoice(
                    aconn,
                    org_id=org_id,
                    org_name=org_name,
                    invoice_id=invoice_id,
                    invoice_no=invoice_no,
                    vendor_names=vendor_names,
                    source="clean",
                    anomaly_type=None,
                    detectability=None,
                )
            )
            if index % 100 == 0 or index == len(clean):
                print(f"  clean {index}/{len(clean)}  ({time.time() - started:.0f}s)", flush=True)

        anomaly_files = sorted(ANOMALY_DIR.glob("*.json"))
        anomaly_files = anomaly_files[:limit] if limit else anomaly_files
        print(f"Anomaly invoices: {len(anomaly_files)}")

        for index, path in enumerate(anomaly_files, start=1):
            meta = manifest_by_no.get(path.stem)
            if meta is None:
                sys.exit(f"[error] {path.name} is not in {MANIFEST.name}")

            invoice, errors = load_invoice(path)
            if invoice is None:
                entries.append(
                    _entry(
                        invoice_key=path.stem,
                        kind=REJECTED_BY_VALIDATION,
                        source="anomaly",
                        anomaly_type=meta["anomaly_type"],
                        detectability=meta["detectability"],
                        inputs={"validation_errors": errors},
                        alerts=[],
                    )
                )
                continue

            invoice_id, existing, vendor_id, vendor_was_created = insert_invoice_for_scoring(
                conn, org_id=org_id, invoice=invoice
            )
            if existing is not None:
                if vendor_was_created:
                    remove_captured_invoice(
                        maint,
                        org_id=org_id,
                        invoice_id=None,
                        vendor_id=vendor_id,
                        vendor_was_created=True,
                    )
                entries.append(
                    await capture_duplicate_check(
                        org_id=org_id,
                        org_name=org_name,
                        vendor_id=vendor_id,
                        vendor_names={**vendor_names, str(vendor_id): invoice.vendor},
                        existing=existing,
                        invoice=invoice,
                        anomaly_type=meta["anomaly_type"],
                        detectability=meta["detectability"],
                    )
                )
                continue

            try:
                entries.append(
                    await capture_scored_invoice(
                        aconn,
                        org_id=org_id,
                        org_name=org_name,
                        invoice_id=invoice_id,
                        invoice_no=invoice.invoice_no,
                        vendor_names={**vendor_names, str(vendor_id): invoice.vendor},
                        source="anomaly",
                        anomaly_type=meta["anomaly_type"],
                        detectability=meta["detectability"],
                    )
                )
            finally:
                remove_captured_invoice(
                    maint,
                    org_id=org_id,
                    invoice_id=invoice_id,
                    vendor_id=vendor_id,
                    vendor_was_created=vendor_was_created,
                )

            if index % 25 == 0 or index == len(anomaly_files):
                print(
                    f"  anomaly {index}/{len(anomaly_files)}  ({time.time() - started:.0f}s)",
                    flush=True,
                )
    finally:
        await aconn.close()
        conn.close()
        maint.close()

    entries.sort(key=lambda e: (e["source"], e["invoice_key"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    write_corpus(out_dir / "corpus.jsonl.gz", entries)
    summary = {
        "captured": summarize(entries),
        "expected_from_dataset": expected_from_dataset(dataset_clean, manifest),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"\nWrote {len(entries)} entries to {out_dir} in {time.time() - started:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", default="Demo Org", help="org holding the loaded dataset")
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, help="capture only the first N of each set (smoke run)")
    parser.add_argument(
        "--maintenance-url",
        default=os.getenv("DATABASE_URL"),
        help="owner connection, used only to delete the anomaly invoices this script inserts "
        "(the application role has no DELETE policy on invoices)",
    )
    args = parser.parse_args()
    if not args.maintenance_url:
        sys.exit("[error] DATABASE_URL is not set and --maintenance-url was not given")
    if args.limit and args.out == DEFAULT_OUT:
        # A truncated corpus is self-consistent: summary.json is regenerated from
        # it, so every coverage check still passes and nothing marks the evidence
        # as partial. Smoke runs write somewhere else.
        sys.exit(
            f"[error] --limit would overwrite the committed corpus at {DEFAULT_OUT}.\n"
            "        Pass --out to a scratch directory for smoke runs."
        )
    asyncio.run(run(args.org, args.out, args.limit, args.maintenance_url))


if __name__ == "__main__":
    main()
