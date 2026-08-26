# Code review — ticket #18 (InvoiceSnapshot, gather adapter, batched Baselines)

**Date:** 2026-08-25
**Fixed point:** `HEAD` = `2ad8e88` — all the work under review is uncommitted in the working tree.
**Branch:** `refactor`
**Spec:** GitHub issue [#18](https://github.com/LingEnOwO/ProcureSight/issues/18), parent [#15](https://github.com/LingEnOwO/ProcureSight/issues/15)

Two axes, reviewed independently in parallel so neither masks the other:

- **Standards** — does the code conform to this repo's documented standards (plus the Fowler smell baseline)?
- **Spec** — does the code faithfully implement what the ticket asked for?

## Files under review

Modified:

- `.claude/CLAUDE.md`
- `CONTEXT.md`
- `apps/api/repos/invoice_stats.py`
- `apps/api/services/anomaly_scoring.py`

New (untracked at review time):

- `apps/api/models/invoice_snapshot.py`
- `apps/api/services/scoring_gather.py`
- `apps/api/tests/test_baseline_selection.py`
- `apps/api/tests/test_invoice_snapshot_gather.py`

Test state at review time: `144 passed` across `apps/api/tests/`, including the 11 golden-corpus replay tests.

---

## Standards

### Hard violation

**`apps/api/services/scoring_gather.py` lines 33–58 — SQL outside `repos/`.**
`.claude/CLAUDE.md`, Key Conventions: "**No ORM:** All database access uses raw psycopg3 queries in `repos/`", reinforced by Code Layout (`repos/` — all SQL queries; `services/` — business logic). `_INVOICE_HEADER_SQL` and `_INVOICE_LINES_SQL` are raw SELECTs executed from a service. Notably the same change *did* put the batched baseline query in `repos/invoice_stats.py`, so the change is internally inconsistent about the rule it breaks. The CLAUDE.md hunk added here describes `scoring_gather.py` as "the one place scoring reads the database" but does not amend the repos rule, so the standard still stands. Mitigation: existing `anomaly_scoring._fetch_invoice_lines` and `evidence_retrieval.py` already inline SQL — precedent exists, but this change is the one claiming to fix the seam. Fix: move both into a repo (e.g. `repos/invoices.py`), leave the adapter as orchestration.

### Judgement calls (baseline smells)

- **Duplicated Code** — `_INVOICE_HEADER_SQL` + `_INVOICE_LINES_SQL` reproduce the column/predicate shape of `anomaly_scoring._fetch_invoice_lines`'s `invoices JOIN invoice_lines … WHERE i.org_id = %(org_id)s AND i.id = %(invoice_id)s`. Two places now read the same rows for scoring; a schema change touches both. Extracting into one repo call resolves this and the violation above together.
- **Speculative Generality** — `scoring_gather.py`: "Nothing consumes the snapshot yet — the rules still read the database themselves." The adapter, `InvoiceSnapshot`, and two test files are unreachable from production paths. Defensible as a deliberately staged refactor behind the committed golden corpus, and the docstring says so; flagging only so the follow-up isn't dropped.
- **Primitive Obsession (weak)** — `invoice: Dict[str, Any]`, `lines: List[Dict[str, Any]]`, `price_baselines: Dict[str, List[Dict[str, Any]]]`. Baseline and Purchased Item are named domain concepts in `CONTEXT.md` yet travel as untyped dict rows. Repo overrides: dict-row plumbing is house style everywhere in `repos/`, so suppress unless the seam is meant to be the typing boundary.

### Clean

- Vocabulary matches `CONTEXT.md`: Baseline, Purchased Item, Invoice snapshot; no "context/bundle/payload".
- `select_price_baseline` correctly lives in `anomaly_scoring.py` as a rule, and honestly documents the ADR-0001 mismatch it preserves rather than silently fixing it.
- `InvoiceSnapshot` as a frozen dataclass in `models/` matches `AlertCandidate` (also a dataclass, not Pydantic) and the amended Code Layout line.
- RLS: `app.org_id` is set in the test `org_id` fixture; `invoice_lines` is covered by its `EXISTS (… invoices …)` policy, so the missing `org_id` predicate on the lines query is correct.
- Async-only fixtures deviate from `test_anomaly_scoring.py`'s sync-to-async bridge, but the docstring justifies it and `conftest.anyio_backend` supports it.

---

## Spec

### (a) Missing / partial

1. > "One gathering adapter builds it; it is the only scoring code that touches the database"

   Not true yet, and the docs assert it as if it were. `apps/api/services/scoring_gather.py` says "the one place scoring reads the database" and `.claude/CLAUDE.md:127` repeats it, while `anomaly_scoring.py` still runs `_fetch_invoice_lines` and `get_vendor_sku_baseline_price` per line in production. The module docstring's later "Nothing consumes the snapshot yet" contradicts its own opening. This AC is inherently only aspirational under the last AC ("No rule consumes the snapshot yet"); the docs should say "will be", not "is".

2. > "Any row-selection rule is a named function in the scoring module, not SQL"

   `select_price_baseline` exists and is well-tested, but it is duplicated from, not moved out of, the live SQL path (`get_vendor_sku_baseline_price` unchanged and still the only caller-facing route). It currently has no production caller. Acceptable for the slice, but the two selections can now drift; only `test_batch_plus_selection_resolves_what_the_per_line_lookup_resolved` pins them together.

3. > "Adapter tests run against real Postgres and assert the batch returns what the per-line lookups returned"

   Met, but the parametrisation (`"Widget"`, `"WIDGET, blue"`, `None`, `"unseen description"`) omits the two edges the equivalence actually turns on: a **tie on `sample_size`**, and a baseline row with a **NULL `desc`**. NULL is in fact safe (SQL `"desc" = %s` and Python `==` both exclude it); ties are not — see (c).

### (b) Scope creep

`_CountingConnection` / `_CountingCursor` and the two query-count assertions sit against #15's explicit testing decision: "does not assert on the number of queries issued or on which repository function was called. Query counts and call sequences are implementation". Defensible, since "a single batched query" is an AC that only a count can check, but it is new test infrastructure the ticket did not ask for.

### (c) Implemented but looks wrong

> "this ticket does not change which Baseline a line resolves to"

The batch orders `ORDER BY sku, sample_size DESC`; the old per-line query ordered `ORDER BY sample_size DESC` alone. Neither has a tiebreaker, so when two rows for one SKU (same `desc` for a described line, any `desc` for a NULL-desc line) share `sample_size`, Postgres may return them in a different relative order under the two-key sort than under the one-key sort — and `select_price_baseline` takes `candidates[0]`. Different median, different alert. Add a deterministic tiebreaker (e.g. `, "desc"`) to both the batch and, for equivalence, the singular helper.

Minor, same theme: `_INVOICE_LINES_SQL` selects `invoice_lines` directly with no `ORDER BY`, where the old rule read lines through a join on `invoices`. Alert ordering is pinned by the golden corpus, so an unordered line read is a latent ordering difference for the next ticket. Also note the snapshot renames columns the rules read (`id` vs `line_id`, no `invoice_total`) — harmless now, load-bearing in #19.

---

## Summary

| Axis | Findings | Worst issue |
| --- | --- | --- |
| Standards | 4 | SQL living in a service instead of `repos/` (hard violation) |
| Spec | 5 | Missing sort tiebreaker — can change which Baseline resolves, so which alert fires |

The two axes are reported separately and deliberately not reranked against each other.

### Suggested follow-up, smallest first

1. ~~Add a deterministic tiebreaker to `get_vendor_unit_price_stats_for_skus` **and** `get_vendor_unit_price_stats`, plus a test that seeds a `sample_size` tie.~~ **Done** — see below.
2. ~~Move `_INVOICE_HEADER_SQL` / `_INVOICE_LINES_SQL` into `repos/invoices.py`; leave `scoring_gather.py` as orchestration.~~ **Done** — see below.
3. ~~Soften the "is the only scoring code that touches the database" wording in `scoring_gather.py` and `.claude/CLAUDE.md` to "will be" until #19 lands.~~ **Done** — see below.
4. ~~Give `_INVOICE_LINES_SQL` an explicit `ORDER BY` before #19 makes line order load-bearing.~~ **Closed as documented, not fixed** — see below.

---

## Fixes applied (2026-08-25, after review)

The two worst findings — one per axis — were fixed. The other two remain open.

**Spec (c), the sort tiebreaker.** Both queries in `apps/api/repos/invoice_stats.py` now order by
`sample_size DESC, "desc"`: the singular/list `get_vendor_unit_price_stats` and the batched
`get_vendor_unit_price_stats_for_skus` (which keeps its leading `sku` key). The view groups by
`(org, vendor, sku, "desc")`, so the description makes the order total rather than expressing a
preference between descriptions — within one SKU the two queries now return rows in the same
relative order by construction. `test_a_tie_on_sample_size_resolves_the_same_way_in_both` seeds two
equally-sampled descriptions under one SKU and a line with no description to narrow by, then asserts
the per-line lookup and batch-plus-`select_price_baseline` pick the same row, and the same row every
run. The golden corpus is unaffected: the tape serves recorded rows and never reaches SQL.

**Standards, SQL outside `repos/`.** `_INVOICE_HEADER_SQL` and `_INVOICE_LINES_SQL` moved into
`apps/api/repos/invoices.py` as `get_invoice_header` and `get_invoice_lines`. They are async, unlike
the rest of that module, which is sync for the worker — a comment records that the sync/async split
is about who calls, not about where SQL lives. `scoring_gather.py` no longer imports `dict_row` and
holds no SQL; it is orchestration over three repo calls. This also settles the **Duplicated Code**
judgement call, since there is now one place to change when the invoice columns change.

**Test state after the fixes:** `145 passed` across `apps/api/tests/` (144 before, plus the new tie
test), including the 11 golden-corpus replay tests.

**Then open:** follow-ups 3 and 4, both since resolved — see the next section.

## Smaller two, resolved (2026-08-25)

**Spec (a)(1), the premature claim.** `scoring_gather.py`'s docstring opened with "the one place
scoring reads the database" and then said, further down, that nothing consumes the snapshot yet.
It now opens with "where scoring *will* read the database" and states plainly that the rules in
`anomaly_scoring` still read it themselves until the next change moves them over. The Code Layout
entry in `.claude/CLAUDE.md` was reworded to match.

**Spec (c) minor, the unordered invoice-lines read — documented rather than changed.** The
mechanical fix is wrong here, so the query is deliberately left unordered and the reasoning is
recorded on `get_invoice_lines` in `apps/api/repos/invoices.py`.

Two rules (`unit_price_delta` and `unapproved_category`) raise one alert per offending line, so line
order decides alert order, and #15 requires alert ordering be preserved. No column reproduces the
order the rules see today: `invoice_lines` has no ordinal and no timestamp, and its `id` is a random
UUID. `ORDER BY id` would therefore be deterministic *and* deterministically different from today's
order on every multi-line invoice — it would create the divergence the finding warns about rather
than prevent it. An unordered read matches the unordered join it replaces, which is the
behaviour-preserving choice.

Note this does not endanger the golden corpus either way: the tape serves recorded invoice rows in
their captured order and never reaches this query. The exposure is production alert ordering only.

A real fix needs a line-ordinal column on `invoice_lines`. That is a schema change, which #15 rules
out ("No schema change"), so it belongs in its own ticket.

**Test state:** `145 passed`, unchanged by these two — the first is wording, the second is a comment.
