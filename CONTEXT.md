# ProcureSight

Multi-tenant invoice processing. Organisations upload invoices, the system extracts
structured data from them, and scores them against historical baselines to raise alerts
about anomalous spend.

## Language

### Purchasing

**Vendor**:
A supplier an organisation buys from. Scoped to one org.
_Avoid_: Supplier, merchant, seller

**Purchased Item**:
A distinct thing an organisation buys from a vendor, identified by `(org_id, vendor_id, sku)`.
Two invoice lines with the same vendor and SKU refer to the same purchased item, whatever
their descriptions say.
_Avoid_: Product, article, material

**SKU**:
The vendor's identifier for a purchased item. The only field that carries item identity.
May be absent on a line, in which case that line has no identifiable purchased item and is
excluded from price baselines.
_Avoid_: Part number, item code, product ID

**Line Description**:
Free text on an invoice line describing what was bought. Human-facing and non-normalised —
it varies with wording, casing and extraction noise, and carries no identity.
_Avoid_: Item name, product name

### Scoring

**Baseline**:
An aggregate of a vendor's history used as the comparison point when scoring a new invoice —
for example the median unit price for a purchased item, or a vendor's typical invoice total.

**Alert**:
A finding raised against one invoice when it deviates from a baseline or violates a contract term.
_Avoid_: Flag, warning, exception

**Alert candidate**:
An Alert a producer has decided to raise but that has not been persisted yet. Every alert-producing
entry point returns these, and the alerts repository is the only thing that turns them into Alerts.
It is the shared output contract of the scoring seam, so it lives in `apps/api/models/alert.py`
rather than inside any one producer.
_Avoid_: Proposed alert, draft alert, pending alert

**Golden corpus**:
The recorded output of the scorer over the whole dataset, plus the database reads that produced
it, stored as data in `dataset/golden/`. Replaying it is how a scoring change proves it changed
no alerts. See `dataset/golden/README.md`.
_Avoid_: Snapshot tests, fixtures
