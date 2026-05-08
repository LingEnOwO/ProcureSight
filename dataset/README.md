# ProcureSight Synthetic Dataset

A realistic, reproducible synthetic procurement dataset for testing the ProcureSight invoice processing pipeline, anomaly detection engine, and RAG retrieval system.

---

## Quick Start

```bash
cd /path/to/ProcureSight
source venv/bin/activate
pip install faker pandas numpy reportlab pillow

python dataset/generators/run_all.py
```

All output lands in `dataset/generated/` (gitignored). Re-running with the same seed produces identical data.

---

## Directory Structure

```
dataset/
├── sample/                     # Small representative examples (committed)
│   ├── invoices_json/          # 5 sample JSON invoices
│   ├── invoices_csv/           # 1 sample CSV (multi-vendor, multi-invoice)
│   ├── invoices_pdf/           # 4 sample PDFs (one per template)
│   ├── contracts/              # 3 sample vendor contracts
│   └── policies/               # 2 sample procurement policies
│
├── generated/                  # Full dataset (gitignored, ~2,000–5,000 files)
│   ├── invoices_json/          # One .json per invoice
│   ├── invoices_csv/           # One .csv per vendor (denormalized)
│   ├── invoices_pdf/           # One .pdf per invoice (multiple templates)
│   ├── contracts/              # One .txt + .md per vendor
│   ├── policies/               # Procurement policy documents
│   └── anomalies.json          # Anomaly manifest (50–100 records)
│
├── generators/
│   ├── run_all.py              # Master pipeline script
│   ├── generate_dataset.py     # Invoice generator (JSON, CSV, PDF)
│   ├── generate_contracts.py   # Contract and policy generator
│   ├── inject_anomalies.py     # Anomaly injector
│   └── utils.py                # Vendor catalog, pricing helpers
│
├── configs/
│   └── generation_config.yaml  # Tunable generation parameters
│
└── README.md
```

---

## Schema Alignment

All generated invoices follow the ProcureSight extraction schema exactly.

### Invoice-Level Fields

| Field          | Type            | Notes                              |
|----------------|-----------------|------------------------------------|
| `invoice_no`   | string          | Unique per invoice                 |
| `vendor`       | string          | Canonical vendor name              |
| `invoice_date` | string (ISO)    | YYYY-MM-DD                         |
| `due_date`     | string \| null  | YYYY-MM-DD or null (6% of invoices)|
| `currency`     | string (ISO 4217)| USD, EUR, or JPY                  |
| `subtotal`     | number          | Sum of line totals                 |
| `tax`          | number          | subtotal × vendor tax rate         |
| `total`        | number          | subtotal + tax                     |
| `lines`        | array           | See below                          |

### Line Item Fields

| Field        | Type           | Notes                              |
|--------------|----------------|------------------------------------|
| `sku`        | string \| null | Null for ~5–30% of lines by vendor |
| `desc`       | string         | Human-readable product description |
| `qty`        | number         | Integer for most products          |
| `unit_price` | number         | From vendor product catalog        |
| `line_total` | number         | qty × unit_price (rounded)         |

### Numerical Invariants

- `line_total ≈ qty × unit_price` (rounded to 2 decimal places)
- `total ≈ subtotal + tax`
- `subtotal = Σ line_total`

---

## Generation Logic

### Vendor Catalog (30 vendors)

Eight procurement categories with stable product catalogs:

| Category                  | Vendors                                              | Invoice Cadence |
|---------------------------|------------------------------------------------------|-----------------|
| Office Supplies           | Apex Office Supply, Stationery World, BlueSky Office | Monthly         |
| IT Hardware               | Cedar Industrial, TechStream, Orion Electronics      | Quarterly       |
| SaaS / Software           | Nexus Cloud, Dataflow Analytics, SecureEdge, ProjSync, DataVault | Monthly |
| Logistics / Shipping      | SwiftRoute, Meridian Freight, EuroShip, FleetWise    | Monthly         |
| Manufacturing Materials   | Pacific Metals, Greenfield Polymers, Nippon Industrial | Monthly/Quarterly |
| Cleaning Services         | BrightSpace Facility, GreenClean Janitorial          | Monthly         |
| Consulting                | Vantage Strategy, Turing Advisory, Meridian HR, Summit Legal | Monthly/As-needed |
| Facility Maintenance      | ProBuild, Vertex Fire, AllGreen, SafePath, IronCore, Cascade | Quarterly/Monthly |

### Invoice Date Distribution

- 18 months of history (from ~18 months ago to yesterday)
- Dates follow each vendor's cadence with ±jitter
- "As-needed" vendors get 2–8 invoices spread randomly

### Pricing Model

- Unit prices sampled from `Gaussian(mean, std)` defined per product
- Quantities sampled from `Gaussian(mean, std)` and clamped to ≥1
- Prices are stable across the vendor's history (same Gaussian, same seed)
- This creates realistic pricing variance while maintaining RAG-retrievable baselines

### Currencies

- USD: ~92% of invoices (all domestic vendors)
- EUR: EuroShip GmbH (European logistics)
- JPY: Nippon Industrial Materials (Japanese manufacturing supplier)

---

## Anomaly Injection Strategy

Anomalies are injected **after** clean invoice generation by copying and modifying existing invoices. Each anomaly gets a new invoice number prefixed `ANOM-NNNN-` so it can be identified.

### Anomaly Types

| Type                    | Severity | Count (approx) | Description                                    |
|-------------------------|----------|----------------|------------------------------------------------|
| `price_spike`           | High     | ~15            | Unit price 3–5.5× vendor baseline              |
| `quantity_spike`        | Medium   | ~11            | Qty 4–6× normal for that product               |
| `tax_mismatch`          | Medium   | ~8             | Tax computed at wrong rate (0%, 15%, 20%, 25%) |
| `vendor_name_variation` | Low      | ~8             | Alternate spelling of canonical vendor name    |
| `duplicate_invoice_no`  | High     | ~6             | Same invoice_no as an existing invoice         |
| `duplicate_submission`  | High     | ~6             | Identical invoice submitted twice              |
| `out_of_cadence`        | Medium   | ~6             | Invoice dated 2–4× outside normal cadence      |
| `negative_line_item`    | Medium   | ~6             | Negative qty on one line item                  |
| `unusual_currency`      | Medium   | ~5             | Vendor billed in unexpected currency           |
| `excessive_consulting`  | High     | ~4             | Consulting total 3–6× typical monthly spend    |

### Anomaly Manifest

`dataset/generated/anomalies.json` contains one record per injected anomaly:

```json
[
  {
    "invoice_no":   "ANOM-0001-INV-2024-V05-0003",
    "anomaly_type": "price_spike",
    "severity":     "high",
    "explanation":  "Line item '27\" 4K IPS Monitor' has unit_price 2,637.80 (4.8x the baseline of 549.00) — far outside historical range for vendor Cedar Industrial Tools."
  }
]
```

---

## PDF Templates

Three visual layouts are distributed round-robin across invoices:

| Template   | Style                                      | Page Size |
|------------|--------------------------------------------|-----------|
| `standard` | Corporate blue header, color-banded rows   | Letter    |
| `modern`   | Green accent, minimal borders, clean type  | Letter    |
| `compact`  | Dense A4 format, dark header row           | A4        |

**Scanned simulation** (~12% of PDFs): Pages are rendered, then processed with:
- Random rotation (±1.2°)
- Gaussian blur (radius 0.2–0.6)
- Brightness/contrast variation

This simulates OCR-challenging scanned documents for extraction pipeline stress-testing.

Multi-page PDFs are generated automatically for invoices with >10 line items via ReportLab's `SimpleDocTemplate` with `repeatRows=1` on the table header.

---

## Contracts & Policies

### Vendor Contracts

One contract per vendor (30 contracts × 2 formats = 60 files):

- `.txt` — plain text for direct ingestion
- `.md` — Markdown for structured retrieval

Each contract contains:
- Approved product catalog with pricing ranges
- Annual spending caps
- Payment terms (Net 30/45/60)
- Volume discount thresholds
- Penalty clauses (1–2.5%/month)
- Renewal terms (auto or manual, 12/24/36 month terms)
- Invoice requirements (referenced for anomaly detection)

### Procurement Policies

Five policy documents:

| File                                      | Topics                                              |
|-------------------------------------------|-----------------------------------------------------|
| `procurement_policy_general.md`           | Approval thresholds, PO requirements, invoice flow  |
| `procurement_policy_reimbursements.md`    | Employee expense limits, receipts, deadlines        |
| `procurement_policy_vendor_management.md` | Onboarding, naming standards, spend concentration   |
| `procurement_policy_compliance.md`        | Three-way match, segregation of duties, fraud       |
| `procurement_policy_it_hardware.md`       | Standard equipment, software procurement, asset mgmt|

---

## RAG Retrieval Considerations

The dataset is designed to support meaningful semantic and keyword retrieval.

### Retrieval Chains

**Query:** "Is toner at $180 per unit reasonable for Apex Office Supply?"

Expected retrievals:
1. Historical toner invoices (AOS-TNR, ~$89.99 baseline)
2. Apex Office Supply vendor contract (pricing clause)
3. `price_spike` anomaly manifest entries for toner
4. General procurement policy (approval thresholds for price overrides)

**Query:** "What are the payment terms for EuroShip?"

Expected retrievals:
1. EuroShip GmbH contract (Net 30, EUR, 19% VAT)
2. Historical EuroShip invoices
3. Currency control policy (EUR payments require Director approval)

### Recommended Embedding Targets

For pgvector indexing:

| Collection              | Content to embed                                      |
|-------------------------|-------------------------------------------------------|
| `invoice_lines`         | `desc` field (product descriptions for semantic search)|
| `vendor_contracts`      | Full contract text, chunked by Article               |
| `policies`              | Policy sections, chunked by heading                  |
| `anomaly_explanations`  | `explanation` field (natural-language anomaly context)|

### Recommended PostgreSQL Mappings

```sql
-- Invoice header → raw_docs / invoices table (existing schema)
invoice_no      VARCHAR(100) PRIMARY KEY
vendor          VARCHAR(255)
invoice_date    DATE
due_date        DATE
currency        CHAR(3)
subtotal        NUMERIC(15, 2)
tax             NUMERIC(15, 2)
total           NUMERIC(15, 2)

-- Line items → invoice_lines table
sku             VARCHAR(100)
desc            TEXT
qty             NUMERIC(10, 3)
unit_price      NUMERIC(15, 2)
line_total      NUMERIC(15, 2)

-- Vendor pricing history → vendor_unit_price_stats (existing view)
-- Feed: invoice_lines grouped by (vendor, desc/sku) over time

-- Anomaly manifest → anomalies table
invoice_no      VARCHAR(100) REFERENCES invoices
anomaly_type    VARCHAR(50)
severity        VARCHAR(10)   -- low / medium / high
explanation     TEXT
```

---

## Reproducibility

All generation uses `random.seed(42)` and `numpy.random.seed(42)`.

Re-running `python dataset/generators/run_all.py` on any machine produces byte-identical output (assuming the same Python version and library versions).

To generate a different dataset, change `seed` in `configs/generation_config.yaml`.
