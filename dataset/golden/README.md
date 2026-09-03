# Scoring golden corpus

`scoring/corpus.jsonl.gz` records what the anomaly scorer produced for every
invoice in the dataset — 2,349 clean and all 337 anomalies from
`dataset/generated/anomalies.json`, `future_rag` included — as of the capture
below. It exists so that the scoring/DB seam refactor
([#15](https://github.com/LingEnOwO/ProcureSight/issues/15)) can prove it changed
nothing.

It is **data, not a test fixture**. It lives here rather than under
`apps/api/tests/` because it has to outlive the database-backed scoring fixtures
that #15 deletes.

## Reading it

One JSON object per line, sorted by `(source, invoice_key)`:

| Field | Meaning |
| --- | --- |
| `invoice_key` | `invoice_no` — stable across dataset loads, unlike the database's UUIDs. Unique only with `source`: the 28 duplicate anomalies carry the number of the invoice they duplicate |
| `kind` | `scored`, `duplicate_check`, or `rejected_by_validation` |
| `source` | `clean` or `anomaly` |
| `anomaly_type`, `detectability` | copied from the manifest; `null` for clean invoices |
| `inputs` | every database read the scorer made for this invoice — see below |
| `alerts` | the alerts it produced, complete and **in order** |

Each alert records `type`, `severity`, `message`, the whole `meta` object, and
`org_id`/`invoice_id`/`vendor_id`. Invoices that produced no alerts are recorded
with `"alerts": []` — a missing entry and a quiet entry say very different
things, and an emptied corpus is exactly what a snapshot-assembly bug looks like.

`inputs` for a `scored` entry is a *tape*: the invoice header and lines, the
un-narrowed `vendor_unit_price_stats` rows for each (vendor, sku, desc) the
scorer looked up, the vendor spend stats, the vendor contract, and — for
`excessive_consulting` — the query it embedded and the chunks it retrieved. That
rule filters on a similarity floor against a live embedding API, so without the
captured chunks its output is not reproducible and it could not be part of any
equivalence check. Replay serves those chunks only for the query they were
retrieved for; a rule that starts asking a different question gets an error
rather than stale evidence.

Price baselines are additionally recorded keyed by **(vendor, sku) with no
description**. Nothing reads them today — the current rule looks up one line at a
time, description included. #15 replaces that with a single fetch keyed by the
invoice's SKUs, a call this tape would otherwise have no answer for, and a corpus
that had to be recaptured from the refactored scorer would prove nothing. Per
ADR-0001 the description carries no identity, so these are the un-narrowed rows
for the same keys. (Across the corpus, 15 of 13,174 such lookups return more than
one description — the regrouping's blast radius, measured in advance.)

Values keep their database types: `{"__dec__": "39.87"}`, `{"__date__": ...}`,
`{"__uuid__": ...}`. The scorer's `meta` and messages carry those types through,
so flattening them would hide a real change.

Identifiers are rewritten at capture time to values derived from dataset names
(`uuid5` of the invoice number, vendor name, …), in inputs and alerts alike. The
scorer only copies ids through, so replay stays exact while the corpus stops
churning every time the database hands out fresh UUIDs.

`summary.json` holds two blocks: `captured`, the counts derived from the corpus
itself, and `expected_from_dataset`, what the dataset said should be covered,
recorded at capture time. `dataset/generated/` is not committed, so that second
block is what lets the replay check verify coverage in CI. Together they are the
quickest way to see that a recapture went wrong.

## Checking it

    pytest apps/api/tests/test_scoring_golden_corpus.py

Replays every entry through the real scorer with the tape serving the reads.
No database, no ARQ, no network; about a second for all 2,686 entries. A read
the tape never recorded raises rather than silently scoring differently.

A failure means the change alters what an operator sees. If that is deliberate,
recapture — never hand-edit the corpus.

## Regenerating it

Capture must happen **before** scoring code moves. Captured afterwards it records
the new behaviour and proves nothing.

1. `make up && make seed`
2. `python scripts/upload_clean_invoices.py`, then wait for the ARQ worker to
   drain — the database must hold exactly the 2,349 clean invoices, and capture
   refuses to run otherwise.
3. `python scripts/index_documents.py` — `excessive_consulting` retrieves from
   `doc_chunks`; with none indexed it silently finds nothing.
4. `export OPENAI_API_KEY=...` (capture aborts without it, for the same reason)
5. `make scoring-corpus`
6. If `anomalies.json` or the clean invoice set changed, update `DATASET_CLEAN`,
   `DATASET_ANOMALIES` and `DATASET_ANOMALIES_BY_DETECTABILITY` in
   `apps/api/tests/test_scoring_golden_corpus.py` to match. `dataset/generated/`
   is not committed, so those constants are the only dataset counts CI can check
   against — and the only ones a truncated capture cannot satisfy.

For a smoke run, `--limit N` needs an `--out` somewhere else; it refuses to write
here. A truncated corpus regenerates `summary.json` from itself, so it is
self-consistent and passes every check except those constants.

Anomaly invoices are deliberately *not* loaded first. Capture inserts each one,
scores it, and deletes it again, so every anomaly is scored against the clean
history — the same position the injection run puts it in — and the database is
left as it was found. (`scripts/upload_anomaly_invoices.py` uploads only the
`current_rules` types and keeps them; it is for demoing the app, not for this.)

Deleting those temporary rows needs `DATABASE_URL`, the owner connection: the
application role has no DELETE policy on `invoices`, so a delete under
`DATABASE_APP_URL` removes nothing and reports no error.

## What this corpus does not cover

Two of the five alert producers never fire anywhere in it, so a refactor cannot
lean on it for their behaviour:

- **`vendor_volume_spike`** — the rule needs five vendor invoices inside a
  30- or 90-day window ending *today*, and the dataset's newest invoice is dated
  2026-05-05. Every vendor's baseline is therefore empty and the rule cannot
  fire. This is time-dependent: the same capture run before ~2026-08-03 would
  have produced coverage. Regenerating the dataset with current dates would fix
  it.
- **`contract_policy_violation`** — `vendor_contracts` is empty in the seeded
  database, so the rule returns before doing any work.

Both need rule-level tests over hand-written inputs, which is what #15's primary
seam is for.

A recapture is also not byte-identical. Two consecutive runs differed in 35 of
2,686 entries: 34 because `excessive_consulting` retrieval depends on a live
embedding API and pgvector ordering, and 1 because `_fetch_invoice_lines` has no
`ORDER BY`, so line order — and with it per-line alert order and `line_id`
numbering — is whatever Postgres returns. Every aggregate in `summary.json` was
identical across both runs. Neither wobble affects replay, which reads the
recorded chunks and the recorded order; it means a recapture diff needs reading
rather than trusting.

## Capture provenance

| | |
| --- | --- |
| Captured | 2026-08-14 |
| Commit | `ceb00fd` (before any scoring code moved) |
| Source org | `Demo Org`, 2,349 clean invoices, 44 vendors, 665 indexed chunks |
| Entries | 2,686 — 2,349 clean, 337 anomaly (277 `current_rules`, 60 `future_rag`) |
| Alerts | 256 `unit_price_delta`, 28 `duplicate_invoice`, 14 `excessive_consulting` |
