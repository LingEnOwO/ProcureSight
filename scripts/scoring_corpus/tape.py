"""The golden corpus format, and the replay harness that reads it.

A corpus entry is a *tape*: every database read the scorer made for one invoice,
plus the alerts it produced. Replaying a tape re-runs the real scoring code with
those reads served from the tape instead of from Postgres, so the corpus can be
checked long after the database that produced it is gone.

Two things keep the tape honest:

* **Values keep their types.** Postgres hands the scorer ``Decimal``, ``date``
  and ``UUID`` objects, and those types reach ``meta`` and the message strings.
  The codec below round-trips them exactly rather than flattening to JSON
  scalars, so a refactor that changes a ``Decimal`` into a ``float`` shows up as
  a corpus diff.
* **An unrecorded read is an error.** Every stub raises if the tape has no entry
  for the key it was asked for. A tape that replays is a tape that captured
  every read the scorer makes.

Identifiers are rewritten to values derived from dataset-stable names (invoice
number, vendor name) at capture time, in the inputs and the alerts alike. The
scorer only ever copies ids through, so replay is exact — and the corpus does
not change just because the database was reloaded and handed out fresh UUIDs.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import importlib
import json
import pathlib
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional, Set, Union

from apps.api.services.anomaly_scoring import AlertCandidate

# Namespace for the synthetic identifiers written into the corpus. Fixed so that
# regenerating the corpus on a fresh database produces the same ids.
ID_NAMESPACE = uuid.UUID("6f1f0c26-5d0f-5c4a-9b6e-0e2f1a7a3d10")

# The raw_doc id recorded for duplicate pre-checks. Capture never ingests a file,
# so there is no real one; the value is pinned rather than invented per run.
CAPTURE_RAW_DOC_ID = 0


def synthetic_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, kind + ":" + ":".join(parts)))


def chunk_fingerprint(chunk_text: str) -> str:
    return hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()[:32]


# ── Codec ────────────────────────────────────────────────────────────────────
# JSON with tagged objects for the types psycopg returns. Keeps the corpus
# diffable while preserving the distinctions the scorer can observe.

def encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"__dec__": str(value)}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, uuid.UUID):
        return {"__uuid__": str(value)}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def decode(value: Any) -> Any:
    if isinstance(value, dict):
        if len(value) == 1:
            [(tag, payload)] = value.items()
            if tag == "__dec__":
                return Decimal(payload)
            if tag == "__datetime__":
                return datetime.fromisoformat(payload)
            if tag == "__date__":
                return date.fromisoformat(payload)
            if tag == "__uuid__":
                return uuid.UUID(payload)
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def stats_key(vendor_id: str, sku: Optional[str], desc: Optional[str]) -> str:
    """Key for one ``vendor_unit_price_stats`` read, as a JSON-object-safe string."""
    return json.dumps([str(vendor_id), sku, desc], ensure_ascii=False)


def alert_to_json(alert: AlertCandidate) -> Dict[str, Any]:
    return {
        "org_id": alert.org_id,
        "invoice_id": alert.invoice_id,
        "vendor_id": alert.vendor_id,
        "type": alert.type,
        "severity": alert.severity,
        "message": alert.message,
        "meta": encode(alert.meta),
    }


def alert_from_json(payload: Dict[str, Any]) -> AlertCandidate:
    return AlertCandidate(
        org_id=payload["org_id"],
        invoice_id=payload["invoice_id"],
        vendor_id=payload["vendor_id"],
        type=payload["type"],
        severity=payload["severity"],
        message=payload["message"],
        meta=decode(payload["meta"]),
    )


# ── Tape ─────────────────────────────────────────────────────────────────────

@dataclass
class ScoringTape:
    """Every read ``score_invoice`` made for one invoice."""

    org_id: str
    invoice_id: str
    invoice_rows: List[Dict[str, Any]] = field(default_factory=list)
    # stats_key(vendor, sku, desc) -> rows, un-narrowed and in the order the
    # view returned them; row selection is the scorer's business, not the tape's.
    unit_price_stats: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    # str(vendor_id) -> rows
    spend_stats: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    # str(vendor_id) -> contract row or None
    contracts: Dict[str, Optional[Dict[str, Any]]] = field(default_factory=dict)
    # The single excessive_consulting retrieval, when the rule reached it.
    retrieval: Optional[Dict[str, Any]] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "org_id": self.org_id,
            "invoice_id": self.invoice_id,
            "invoice_rows": encode(self.invoice_rows),
            "unit_price_stats": {k: encode(v) for k, v in self.unit_price_stats.items()},
            "spend_stats": {k: encode(v) for k, v in self.spend_stats.items()},
            "contracts": {k: encode(v) for k, v in self.contracts.items()},
            "retrieval": encode(self.retrieval),
        }

    @classmethod
    def from_json(cls, payload: Dict[str, Any]) -> "ScoringTape":
        return cls(
            org_id=payload["org_id"],
            invoice_id=payload["invoice_id"],
            invoice_rows=decode(payload["invoice_rows"]),
            unit_price_stats={k: decode(v) for k, v in payload["unit_price_stats"].items()},
            spend_stats={k: decode(v) for k, v in payload["spend_stats"].items()},
            contracts={k: decode(v) for k, v in payload["contracts"].items()},
            retrieval=decode(payload["retrieval"]),
        )


@dataclass
class DuplicateCheckTape:
    """The inputs to the pre-insert duplicate check, which reads nothing itself."""

    org_id: str
    vendor_id: str
    existing: Dict[str, Any]
    incoming_invoice_no: str
    incoming_vendor: str
    incoming_total: float
    incoming_raw_doc_id: int = CAPTURE_RAW_DOC_ID

    def to_json(self) -> Dict[str, Any]:
        return {
            "org_id": self.org_id,
            "vendor_id": self.vendor_id,
            "existing": encode(self.existing),
            "incoming_invoice_no": self.incoming_invoice_no,
            "incoming_vendor": self.incoming_vendor,
            "incoming_total": self.incoming_total,
            "incoming_raw_doc_id": self.incoming_raw_doc_id,
        }

    @classmethod
    def from_json(cls, payload: Dict[str, Any]) -> "DuplicateCheckTape":
        return cls(
            org_id=payload["org_id"],
            vendor_id=payload["vendor_id"],
            existing=decode(payload["existing"]),
            incoming_invoice_no=payload["incoming_invoice_no"],
            incoming_vendor=payload["incoming_vendor"],
            incoming_total=payload["incoming_total"],
            incoming_raw_doc_id=payload["incoming_raw_doc_id"],
        )


class MissingTapeRead(KeyError):
    """The scorer asked for something the tape did not record."""


# ── The seam ─────────────────────────────────────────────────────────────────
#
# The five reads scoring makes, and where each is looked up. Capture wraps them
# to record; replay replaces them to serve. Both go through `intercepting`, so a
# sixth read is added here once rather than in two places.
#
# The price and spend stats are intercepted at the *plural* repository functions
# even though the scorer calls the singular helpers: those helpers narrow (order
# by sample size, take the first row), and the corpus is about what the database
# returned before any narrowing.

SEAM = {
    "_fetch_invoice_lines": "apps.api.services.anomaly_scoring",
    "get_vendor_contract": "apps.api.services.anomaly_scoring",
    "_search_chunks_async": "apps.api.services.anomaly_scoring",
    "get_vendor_unit_price_stats": "apps.api.repos.invoice_stats",
    "get_vendor_spend_stats": "apps.api.repos.invoice_stats",
}


def seam_module(name: str) -> Any:
    return importlib.import_module(SEAM[name])


def seam_function(name: str) -> Any:
    """The function currently installed at a seam point — the real one, unless
    an ``intercepting`` block is active."""
    return getattr(seam_module(name), name)


@contextmanager
def intercepting(**replacements: Any) -> Iterator[None]:
    """Swap seam functions for the duration, then put the originals back."""
    unknown = set(replacements) - set(SEAM)
    if unknown:
        raise KeyError(f"not part of the scoring seam: {sorted(unknown)}")

    originals = [(seam_module(n), n, getattr(seam_module(n), n)) for n in replacements]
    for name, replacement in replacements.items():
        setattr(seam_module(name), name, replacement)
    try:
        yield
    finally:
        for module, name, original in originals:
            setattr(module, name, original)


# ── Replay ───────────────────────────────────────────────────────────────────

@contextmanager
def served_from(tape: ScoringTape) -> Iterator[None]:
    """Serve the scorer's database reads from ``tape`` for the duration."""

    async def fetch_invoice_lines(db: Any, *, org_id: str, invoice_id: str) -> List[Dict[str, Any]]:
        return [dict(row) for row in tape.invoice_rows]

    async def unit_price_stats(
        db: Any,
        *,
        org_id: str,
        vendor_id: Optional[str] = None,
        sku: Optional[str] = None,
        desc: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        key = stats_key(str(vendor_id), sku, desc)
        if key not in tape.unit_price_stats:
            raise MissingTapeRead(f"unit price stats not recorded for {key}")
        return [dict(row) for row in tape.unit_price_stats[key]]

    async def spend_stats(
        db: Any, *, org_id: str, vendor_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        key = str(vendor_id)
        if key not in tape.spend_stats:
            raise MissingTapeRead(f"spend stats not recorded for vendor {key}")
        return [dict(row) for row in tape.spend_stats[key]]

    async def vendor_contract(db: Any, *, org_id: str, vendor_id: str) -> Optional[Dict[str, Any]]:
        key = str(vendor_id)
        if key not in tape.contracts:
            raise MissingTapeRead(f"contract lookup not recorded for vendor {key}")
        contract = tape.contracts[key]
        return dict(contract) if contract is not None else None

    async def search_chunks(
        db: Any,
        org_id: str,
        query: str,
        source_types: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        if tape.retrieval is None:
            raise MissingTapeRead("chunk retrieval not recorded for this invoice")
        # The query text is rule-owned — which lines count as consulting, and how
        # they are phrased into a query. Serving recorded chunks for a different
        # question would hide exactly the change worth catching.
        asked = (query, source_types, limit)
        recorded = (
            tape.retrieval["query"],
            tape.retrieval["source_types"],
            tape.retrieval["limit"],
        )
        if asked != recorded:
            raise MissingTapeRead(
                f"chunks were retrieved for a different query:\n"
                f"  recorded: {recorded!r}\n  asked   : {asked!r}"
            )
        return [dict(chunk) for chunk in tape.retrieval["chunks"]]

    with intercepting(
        _fetch_invoice_lines=fetch_invoice_lines,
        get_vendor_contract=vendor_contract,
        _search_chunks_async=search_chunks,
        get_vendor_unit_price_stats=unit_price_stats,
        get_vendor_spend_stats=spend_stats,
    ):
        yield


async def replay_scoring_async(tape: ScoringTape) -> List[AlertCandidate]:
    """Run the real scorer over a tape. No database, no network."""
    from apps.api.services.anomaly_scoring import score_invoice

    with served_from(tape):
        return await score_invoice(None, org_id=tape.org_id, invoice_id=tape.invoice_id)


def replay_scoring(tape: ScoringTape) -> List[AlertCandidate]:
    return asyncio.run(replay_scoring_async(tape))


def replay_duplicate_check(tape: DuplicateCheckTape) -> List[AlertCandidate]:
    from apps.api.services.anomaly_scoring import build_duplicate_alert

    return [
        build_duplicate_alert(
            org_id=tape.org_id,
            vendor_id=tape.vendor_id,
            existing=tape.existing,
            incoming_invoice_no=tape.incoming_invoice_no,
            incoming_vendor=tape.incoming_vendor,
            incoming_total=tape.incoming_total,
            incoming_raw_doc_id=tape.incoming_raw_doc_id,
        )
    ]


# ── Corpus entries ───────────────────────────────────────────────────────────

# Entry kinds. Not every dataset invoice reaches the scorer: 28 anomalies are
# rejected pre-insert as duplicates, and extraction can reject a document
# outright. Both are recorded rather than omitted — a missing entry and an
# entry with no alerts say very different things.
SCORED = "scored"
DUPLICATE_CHECK = "duplicate_check"
REJECTED_BY_VALIDATION = "rejected_by_validation"


async def replay_entry_async(entry: Dict[str, Any]) -> List[AlertCandidate]:
    """Re-run the scorer for one corpus entry and return the alerts it produces."""
    if entry["kind"] == DUPLICATE_CHECK:
        return replay_duplicate_check(DuplicateCheckTape.from_json(entry["inputs"]))
    if entry["kind"] == REJECTED_BY_VALIDATION:
        # Extraction rejected the document, so the scorer never saw it.
        return []
    return await replay_scoring_async(ScoringTape.from_json(entry["inputs"]))


def replay_entry(entry: Dict[str, Any]) -> List[AlertCandidate]:
    return asyncio.run(replay_entry_async(entry))


def expected_alerts(entry: Dict[str, Any]) -> List[AlertCandidate]:
    return [alert_from_json(a) for a in entry["alerts"]]


# ── Summary ─────────────────────────────────────────────────────────────────

def expected_from_dataset(
    clean_invoice_nos: Set[str], manifest: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """What the dataset said the corpus should cover, recorded at capture time.

    ``dataset/generated/`` is not committed, so this is what lets the replay
    check verify coverage in CI, where the dataset it was captured from is gone.
    """
    return {
        "clean_invoices": len(clean_invoice_nos),
        "anomaly_invoices": len(manifest),
        "anomalies_by_detectability": dict(
            Counter(entry["detectability"] for entry in manifest)
        ),
    }


def summarize(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts that make an incomplete or emptied corpus obvious at a glance."""
    with_alerts = [e for e in entries if e["alerts"]]
    return {
        "entries": len(entries),
        "clean": sum(1 for e in entries if e["source"] == "clean"),
        "anomaly": sum(1 for e in entries if e["source"] == "anomaly"),
        "entries_by_kind": dict(Counter(e["kind"] for e in entries)),
        "anomalies_by_detectability": dict(
            Counter(e["detectability"] for e in entries if e["detectability"])
        ),
        "entries_with_alerts": len(with_alerts),
        "entries_without_alerts": len(entries) - len(with_alerts),
        "alerts_by_type": dict(
            Counter(a["type"] for e in entries for a in e["alerts"])
        ),
        "entries_with_retrieved_chunks": sum(
            1 for e in entries if e["kind"] == SCORED and e["inputs"].get("retrieval")
        ),
    }


def _open_corpus(path: Union[str, pathlib.Path], mode: str) -> Any:
    """Corpus files are gzipped by default; an uncompressed path also works."""
    path = pathlib.Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    return opener(path, mode, encoding="utf-8")


def read_corpus(path: Union[str, pathlib.Path]) -> List[Dict[str, Any]]:
    """Read a corpus file — one JSON entry per line, sorted by (source, key)."""
    with _open_corpus(path, "rt") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_corpus(path: Union[str, pathlib.Path], entries: List[Dict[str, Any]]) -> None:
    with _open_corpus(path, "wt") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
