"""Tests for the golden-corpus tape: the codec, and the replay harness.

These cover the machinery, not the corpus. The corpus itself is checked by
test_scoring_golden_corpus.py. No database and no network here — that is the
whole point of the tape.
"""
import inspect
import re
from datetime import date
from decimal import Decimal

import pytest

from apps.api.repos.invoices import get_invoice_header, get_invoice_lines
from scripts.scoring_corpus.tape import (
    _HEADER_FROM_ROW,
    _LINE_FROM_ROW,
    DuplicateCheckTape,
    MissingTapeRead,
    ScoringTape,
    alert_from_json,
    alert_to_json,
    decode,
    encode,
    replay_duplicate_check,
    replay_scoring,
    stats_key,
)

ORG = "11111111-1111-5111-8111-111111111111"
VENDOR = "22222222-2222-5222-8222-222222222222"
INVOICE = "33333333-3333-5333-8333-333333333333"
LINE = "44444444-4444-5444-8444-444444444444"


def _invoice_row(**overrides):
    row = {
        "invoice_id": INVOICE,
        "org_id": ORG,
        "vendor_id": VENDOR,
        "invoice_no": "INV-2026-V01-0001",
        "invoice_date": date(2026, 5, 12),
        "due_date": date(2026, 6, 11),
        "invoice_total": Decimal("1000.00"),
        "line_id": LINE,
        "sku": "AGL-MUL",
        "desc": "Mulch Installation (per cubic yard)",
        "qty": Decimal("1"),
        "unit_price": Decimal("300.00"),
        "line_total": Decimal("300.00"),
    }
    row.update(overrides)
    return row


def _tape(**overrides) -> ScoringTape:
    row = _invoice_row()
    tape = ScoringTape(
        org_id=ORG,
        invoice_id=INVOICE,
        invoice_rows=[row],
        # Keyed by SKU alone: the gathering adapter fetches a Baseline per
        # Purchased Item, and picking between a SKU's description variants is a
        # rule the scorer applies afterwards.
        unit_price_stats={
            stats_key(VENDOR, row["sku"], None): [
                {
                    "org_id": ORG,
                    "vendor_id": VENDOR,
                    "sku": row["sku"],
                    "desc": row["desc"],
                    "sample_size": 12,
                    "median_unit_price": Decimal("100.00"),
                    "mean_unit_price": Decimal("100.00"),
                }
            ]
        },
        spend_stats={VENDOR: []},
        contracts={VENDOR: None},
    )
    for key, value in overrides.items():
        setattr(tape, key, value)
    return tape


# ── Codec ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value",
    [
        Decimal("39.87"),
        Decimal("0.1"),
        date(2026, 5, 12),
        {"nested": [Decimal("1.5"), date(2020, 1, 1), None, "text", 3, True]},
    ],
)
def test_codec_round_trips_database_types(value):
    round_tripped = decode(encode(value))
    assert round_tripped == value
    assert type(round_tripped) is type(value)


def test_codec_keeps_decimal_scale():
    """Trailing zeros are observable — the scorer formats these into messages."""
    assert str(decode(encode(Decimal("100.00")))) == "100.00"


def test_alert_json_round_trip():
    alerts = replay_scoring(_tape())
    assert [alert_from_json(alert_to_json(a)) for a in alerts] == alerts


# ── Replay ───────────────────────────────────────────────────────────────────

def test_replay_scores_from_the_tape_alone():
    alerts = replay_scoring(_tape())

    assert [a.type for a in alerts] == ["unit_price_delta"]
    alert = alerts[0]
    assert alert.severity == "high"  # 300 / 100 = 3x
    assert alert.meta["ratio"] == 3.0
    assert alert.meta["sample_size"] == 12
    assert alert.invoice_id == INVOICE


def test_replay_round_trips_through_json():
    tape = _tape()
    from_disk = ScoringTape.from_json(tape.to_json())
    assert replay_scoring(from_disk) == replay_scoring(tape)


def test_replay_preserves_alert_ordering():
    """Two rules firing on one invoice must come back in the scorer's order."""
    tape = _tape(
        spend_stats={
            VENDOR: [
                {
                    "org_id": ORG,
                    "vendor_id": VENDOR,
                    "invoice_count_30d": 8,
                    "total_spend_30d": Decimal("2000"),
                    "median_invoice_total_30d": Decimal("200.00"),
                    "invoice_count_90d": 10,
                    "total_spend_90d": Decimal("3000"),
                    "median_invoice_total_90d": Decimal("200.00"),
                }
            ]
        },
    )

    assert [a.type for a in replay_scoring(tape)] == [
        "unit_price_delta",
        "vendor_volume_spike",
    ]


def test_replay_records_invoices_that_produce_no_alerts():
    tape = _tape(unit_price_stats={stats_key(VENDOR, "AGL-MUL", None): []})
    assert replay_scoring(tape) == []


def _consulting_tape() -> ScoringTape:
    """An invoice with a consulting line, so excessive_consulting reaches retrieval."""
    row = _invoice_row(
        desc="Management Consulting Services",
        sku="CON-ADV",
        unit_price=Decimal("400.00"),
        qty=Decimal("40"),
        line_total=Decimal("16000.00"),
    )
    return ScoringTape(
        org_id=ORG,
        invoice_id=INVOICE,
        invoice_rows=[row],
        unit_price_stats={stats_key(VENDOR, row["sku"], None): []},
        spend_stats={VENDOR: []},
        contracts={VENDOR: None},
        retrieval={
            "query": (
                "Management Consulting Services consulting rate limit "
                "professional services cap hourly rate"
            ),
            "source_types": ["contract", "policy"],
            "limit": 5,
            "chunks": [
                {
                    "id": "55555555-5555-5555-8555-555555555555",
                    "source_type": "contract",
                    "source_name": "acme-msa.pdf",
                    "chunk_text": "Management Consulting (per hour): $185.00 per unit",
                    "meta_json": None,
                    "similarity": 0.71,
                }
            ],
        },
    )


def test_replay_serves_retrieved_chunks_instead_of_calling_the_embedding_api():
    alerts = replay_scoring(_consulting_tape())

    assert [a.type for a in alerts] == ["excessive_consulting"]
    assert alerts[0].meta["contract_rate_found"] == 185.0
    assert alerts[0].meta["vector_evidence"][0]["source_name"] == "acme-msa.pdf"


def test_replay_refuses_to_invent_a_read_the_tape_is_missing():
    """A tape that missed a read must fail loudly, not silently score differently."""
    tape = _tape(unit_price_stats={})
    with pytest.raises(MissingTapeRead):
        replay_scoring(tape)


def test_replay_refuses_to_serve_chunks_retrieved_for_a_different_question():
    """The retrieval query is rule-owned; serving old chunks for a new query
    would hide a change to what excessive_consulting asks for."""
    tape = _consulting_tape()
    tape.retrieval["query"] = "something the rule no longer asks"

    with pytest.raises(MissingTapeRead, match="different query"):
        replay_scoring(tape)


def test_duplicate_check_replays_without_any_recorded_reads():
    tape = DuplicateCheckTape(
        org_id=ORG,
        vendor_id=VENDOR,
        existing={"id": INVOICE, "total": Decimal("406.33")},
        incoming_invoice_no="INV-2026-V33-0143",
        incoming_vendor="Summit Packaging Solutions",
        incoming_total=406.33,
    )

    alerts = replay_duplicate_check(DuplicateCheckTape.from_json(tape.to_json()))

    assert [a.type for a in alerts] == ["duplicate_invoice"]
    assert alerts[0].severity == "critical"
    assert alerts[0].meta["matched_fields"] == ["vendor_id", "invoice_no", "total"]


# ---------------------------------------------------------------------------
# The replay reprojection
# ---------------------------------------------------------------------------

def _selected_columns(read) -> set:
    """The column names the literal SELECT inside `read` asks for."""
    select = re.search(r"SELECT\n(.*?)\n\s*FROM", inspect.getsource(read), re.S)
    assert select, f"no literal SELECT found in {read.__name__}"
    return {column.strip().strip('"') for column in select.group(1).split(",")}


def test_the_replay_reprojection_covers_every_column_the_snapshot_reads_select():
    """Replay serves the gatherer's two reads out of the recorded joined row.

    `tape.py` states that mapping itself rather than importing it, because a tape
    on disk has the columns it was captured with. That independence is the point,
    but it can go stale silently — a column added to either read would be served
    short, and the rules would see None where the database has a value. This is
    the check that turns that into a failure here instead.

    It guards the column names, not the aliases they are read out from: renaming
    an alias in `_fetch_invoice_lines` still breaks replay silently. Guarding
    that half means parsing a SELECT that aliases, which this regex cannot do.
    """
    assert set(_HEADER_FROM_ROW) == _selected_columns(get_invoice_header)
    assert set(_LINE_FROM_ROW) == _selected_columns(get_invoice_lines)
