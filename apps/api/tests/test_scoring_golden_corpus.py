"""Replay the golden corpus against the current scorer.

This is the check that makes "the refactor changed nothing" a claim the suite
verifies rather than one a reviewer has to take on trust. It needs no database,
no ARQ and no embedding API: every read the scorer makes is served from the
corpus, so it keeps working after the database-backed scoring fixtures are gone.

If this fails after a scoring change, the change altered what an operator sees.
That is either a bug or a deliberate detection change — and a deliberate one is
recaptured (see dataset/golden/README.md), never edited by hand.
"""
import json
import pathlib

import pytest

from scripts.scoring_corpus.tape import (
    DUPLICATE_CHECK,
    SCORED,
    alert_to_json,
    expected_from_dataset,
    read_corpus,
    replay_entry,
    summarize,
)

CORPUS_DIR = pathlib.Path(__file__).resolve().parents[3] / "dataset" / "golden" / "scoring"
DATASET = pathlib.Path(__file__).resolve().parents[3] / "dataset" / "generated"

# How many differing entries to spell out before giving up on the failure message.
MAX_REPORTED_DIFFS = 3


@pytest.fixture(scope="module")
def corpus():
    return read_corpus(CORPUS_DIR / "corpus.jsonl.gz")


@pytest.fixture(scope="module")
def summary():
    return json.loads((CORPUS_DIR / "summary.json").read_text())


# ── Coverage ─────────────────────────────────────────────────────────────────
#
# dataset/generated/ is not committed, so coverage is checked against the counts
# capture recorded from it. The two tests below compare key for key instead, and
# only run where the dataset is actually present.

needs_dataset = pytest.mark.skipif(
    not (DATASET / "anomalies.json").exists(),
    reason="dataset/generated/ is not committed; counts are checked from summary.json",
)

# The dataset's own counts, from anomalies.json and the clean invoice files, written
# down here rather than read from the corpus. Everything else in this file compares
# the corpus against numbers the same capture run produced, so a truncated corpus is
# self-consistent and passes. These are the one check it cannot satisfy.
DATASET_CLEAN = 2349
DATASET_ANOMALIES = 337
DATASET_ANOMALIES_BY_DETECTABILITY = {"current_rules": 277, "future_rag": 60}


def test_corpus_is_the_size_the_dataset_says_it_should_be(corpus, summary):
    """Guards against a partial capture — `make scoring-corpus` cut short, or run
    against a half-loaded database. Change these only alongside the dataset."""
    assert len(corpus) == DATASET_CLEAN + DATASET_ANOMALIES
    assert sum(1 for e in corpus if e["source"] == "clean") == DATASET_CLEAN
    assert sum(1 for e in corpus if e["source"] == "anomaly") == DATASET_ANOMALIES
    assert summary["expected_from_dataset"] == {
        "clean_invoices": DATASET_CLEAN,
        "anomaly_invoices": DATASET_ANOMALIES,
        "anomalies_by_detectability": DATASET_ANOMALIES_BY_DETECTABILITY,
    }


def test_covers_the_whole_dataset_including_future_rag(corpus, summary):
    expected = summary["expected_from_dataset"]
    captured = summary["captured"]

    assert captured["clean"] == expected["clean_invoices"]
    assert captured["anomaly"] == expected["anomaly_invoices"]
    assert (
        captured["anomalies_by_detectability"] == expected["anomalies_by_detectability"]
    ), "future_rag anomalies are real inputs and belong in the corpus"
    # Keyed by (source, invoice_key): the 28 duplicate anomalies carry the
    # invoice number of the clean invoice they duplicate.
    assert len({(e["source"], e["invoice_key"]) for e in corpus}) == len(corpus)


@needs_dataset
def test_covers_every_clean_invoice(corpus):
    expected = {p.stem for p in (DATASET / "invoices_json").glob("INV-*.json")}
    captured = {e["invoice_key"] for e in corpus if e["source"] == "clean"}
    assert captured == expected


@needs_dataset
def test_covers_every_anomaly_in_the_manifest(corpus, summary):
    manifest = json.loads((DATASET / "anomalies.json").read_text())
    clean = {p.stem for p in (DATASET / "invoices_json").glob("INV-*.json")}
    captured = {e["invoice_key"] for e in corpus if e["source"] == "anomaly"}

    assert captured == {entry["invoice_no"] for entry in manifest}
    assert summary["expected_from_dataset"] == expected_from_dataset(clean, manifest)


def test_invoices_producing_no_alerts_are_recorded_not_omitted(corpus):
    """A dropped entry and an entry with no alerts must stay distinguishable."""
    quiet = [e for e in corpus if not e["alerts"]]
    assert len(quiet) > 0
    assert all("inputs" in e for e in quiet)


def test_alert_entries_record_the_full_alert(corpus):
    for entry in corpus:
        for alert in entry["alerts"]:
            assert set(alert) == {
                "org_id",
                "invoice_id",
                "vendor_id",
                "type",
                "severity",
                "message",
                "meta",
            }
            assert alert["meta"]


def test_excessive_consulting_alerts_carry_their_retrieved_chunks(corpus):
    """Without the chunks that rule is not reproducible, so it cannot be replayed."""
    consulting = [
        e for e in corpus if any(a["type"] == "excessive_consulting" for a in e["alerts"])
    ]
    assert consulting
    for entry in consulting:
        retrieval = entry["inputs"]["retrieval"]
        assert retrieval is not None
        assert retrieval["query"]
        assert "chunks" in retrieval


def test_records_baselines_keyed_by_sku_alone(corpus):
    """#15 replaces the per-line lookup with one fetch keyed by the invoice's SKUs.

    Nothing reads these today; they are here so that replay can answer that call
    after the code moves, instead of the corpus needing a recapture from the
    refactored scorer — which would prove nothing.
    """
    checked = 0
    for entry in corpus:
        if entry["kind"] != SCORED:
            continue
        keys = {tuple(json.loads(k)) for k in entry["inputs"]["unit_price_stats"]}
        for row in entry["inputs"]["invoice_rows"]:
            if row["sku"] is None:
                continue
            vendor_id = row["vendor_id"]["__uuid__"]
            assert (vendor_id, row["sku"], None) in keys
            checked += 1
    assert checked > 0


def test_summary_matches_the_corpus(corpus, summary):
    assert summarize(corpus) == summary["captured"]


# ── Replay ───────────────────────────────────────────────────────────────────

def test_every_entry_replays_to_the_same_alerts(corpus):
    differences = []
    for entry in corpus:
        replayed = [alert_to_json(a) for a in replay_entry(entry)]
        if replayed != entry["alerts"]:
            differences.append((entry["invoice_key"], entry["alerts"], replayed))

    if differences:
        report = "\n".join(
            f"  {key}\n    corpus  : {json.dumps(expected, sort_keys=True)[:400]}\n"
            f"    current : {json.dumps(actual, sort_keys=True)[:400]}"
            for key, expected, actual in differences[:MAX_REPORTED_DIFFS]
        )
        pytest.fail(
            f"{len(differences)} of {len(corpus)} corpus entries score differently now:\n{report}"
        )


def test_replay_covers_both_alert_producing_paths(corpus):
    """Scoring an invoice and the pre-insert duplicate check are both replayed."""
    kinds = {e["kind"] for e in corpus}
    assert SCORED in kinds
    assert DUPLICATE_CHECK in kinds
