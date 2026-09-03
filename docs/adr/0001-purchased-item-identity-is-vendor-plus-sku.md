# Purchased item identity is (org, vendor, SKU) — description carries no identity

Within an organisation, a purchased item is identified by `(org_id, vendor_id, sku)`. A line's
`desc` is descriptive text, not part of that identity: two invoice lines with the same vendor and
SKU refer to the same item even when their descriptions differ. Lines without a SKU have no
identifiable purchased item and are excluded from price baselines.

We record this because the code currently says otherwise. The `vendor_unit_price_stats` view
groups by `(org_id, vendor_id, sku, "desc")`, which treats description as identity-bearing. That
grouping appears incidental — grouping by everything projected — rather than decided: within the
generated dataset, all 266 distinct `(vendor, sku)` keys map to exactly one description each, and
`inject_anomalies.py` already matches invoice lines by SKU alone while carrying `desc` unused.

## Considered options

**Description is part of item identity** (what the SQL does today). Defensible if a vendor reuses a
SKU across genuinely different products, where merging would blend unrelated price series into one
median. We found no evidence of that in this codebase — but note the dataset is synthetic and
generated under the same assumption we are adopting here, so it corroborates the decision and
cannot falsify it. If a real tenant is found reusing SKUs, this ADR is the thing to revisit.

**Description carries no identity** (chosen). Invoices arrive as PDFs and are extracted by LLM into
a free-text `desc` with no normalisation anywhere in the ingestion path. Under description-bearing
identity, ordinary extraction drift — rewrapping, casing, truncation — silently forks one item's
history into several under-sampled baselines, each of which then fails the minimum sample size and
leaves the line unscored. That is a false-negative source that grows with extraction noise, and it
is invisible in production because the alert that should have fired simply doesn't.

## Consequences

This ADR records the domain rule only; the implementation still groups by description. Realigning
the view is deferred to its own change, because merging description variants raises sample sizes
and shifts medians, so more invoices become eligible for scoring and detection behaviour moves.
That belongs in a change measured against the labelled anomaly set on its own, not bundled into a
behaviour-preserving refactor. `evidence_retrieval`, which currently matches history on `sku or
desc`, should be revisited at the same time.
