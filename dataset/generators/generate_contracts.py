#!/usr/bin/env python3
"""
Vendor contract and procurement policy generator for ProcureSight.

Writes .txt and .md files to:
  dataset/generated/contracts/
  dataset/generated/policies/

Also writes a small set to:
  dataset/sample/contracts/
  dataset/sample/policies/
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dataset.generators.utils import VENDOR_CATALOG, seed_all, VendorProfile

CONTRACTS_OUT = ROOT / "dataset/generated/contracts"
POLICIES_OUT  = ROOT / "dataset/generated/policies"
SAMPLE_CONTRACTS = ROOT / "dataset/sample/contracts"
SAMPLE_POLICIES  = ROOT / "dataset/sample/policies"

SEED = 42


# ── Contract generation ────────────────────────────────────────────────────────

def _format_currency(amount: float, code: str) -> str:
    sym = {"USD": "$", "EUR": "€", "JPY": "¥"}.get(code, code + " ")
    if code == "JPY":
        return f"{sym}{amount:,.0f}"
    return f"{sym}{amount:,.2f}"


def _spending_limit(vendor: VendorProfile, rng: random.Random) -> float:
    products = vendor.products
    max_price = max(p.unit_price_mean for p in products)
    typical_monthly = max_price * 10
    annual_estimate = typical_monthly * 12
    return round(annual_estimate * rng.uniform(1.2, 2.5), -2)


def _penalty_rate(rng: random.Random) -> str:
    pct = rng.choice([1.0, 1.5, 2.0, 2.5])
    return f"{pct:.1f}% per month"


def generate_contract(
    vendor: VendorProfile,
    contract_no: str,
    rng: random.Random,
    start_date: date,
) -> str:
    term_months = rng.choice([12, 24, 36])
    end_date = start_date + timedelta(days=term_months * 30)
    renewal = rng.choice(["automatic 30-day renewal", "manual renewal required 60 days before expiry",
                          "automatic 12-month renewal"])
    spending_limit = _spending_limit(vendor, rng)
    penalty = _penalty_rate(rng)
    discount = rng.choice([0, 2, 3, 5, 7, 10])
    payment_terms = vendor.payment_terms_days

    products_section = "\n".join(
        f"  - {p.desc}: {_format_currency(p.unit_price_mean, vendor.currency)} "
        f"± {_format_currency(p.unit_price_std, vendor.currency)} per unit"
        for p in vendor.products
    )

    approved_categories = {
        "office_supplies": "office supplies, consumables, and related equipment",
        "it_hardware": "information technology hardware, peripherals, and infrastructure",
        "saas_software": "software-as-a-service subscriptions and digital services",
        "logistics_shipping": "freight, logistics, fulfillment, and shipping services",
        "manufacturing_materials": "raw materials, industrial components, and production supplies",
        "cleaning_services": "janitorial, cleaning, and sanitation services",
        "consulting": "professional consulting, advisory, and staffing services",
        "facility_maintenance": "facility maintenance, repairs, and building services",
    }.get(vendor.category, "goods and services")

    content = f"""VENDOR SERVICES AGREEMENT
==========================

Contract Number : {contract_no}
Agreement Date  : {start_date.isoformat()}
Effective Date  : {start_date.isoformat()}
Expiration Date : {end_date.isoformat()}

PARTIES
-------
Buyer  : ProcureSight Corp.
         123 Business Ave, Suite 400
         San Francisco, CA 94105
         EIN: 47-XXXXXXX

Vendor : {vendor.name}

ARTICLE 1 — SCOPE OF SERVICES
------------------------------
Vendor agrees to supply the following approved categories of goods and services:
{approved_categories.upper()}.

Approved Products and Standard Pricing:
{products_section}

Pricing is denominated in {vendor.currency}. Unit prices are valid for the
term of this agreement and may be adjusted only with 30-day written notice.

ARTICLE 2 — PRICING & DISCOUNTS
---------------------------------
Volume Discount: A {discount}% discount applies to any single order exceeding
{_format_currency(spending_limit * 0.10, vendor.currency)}.

Price Escalation: Prices may increase by no more than 3% per calendar year,
effective upon written notice at least 60 days before the increase takes effect.

ARTICLE 3 — PAYMENT TERMS
--------------------------
Payment Terms : Net {payment_terms}
Invoice Currency : {vendor.currency}
Late Payment Penalty : {penalty}

All invoices must reference this contract number ({contract_no}) and be
submitted to: accounts.payable@procuresight.com

ARTICLE 4 — ANNUAL SPENDING LIMIT
-----------------------------------
ProcureSight's approved annual spend under this agreement is capped at:
{_format_currency(spending_limit, vendor.currency)}

Any order that would cause cumulative annual spend to exceed this cap requires
written approval from the VP of Finance before the order is placed.

ARTICLE 5 — INVOICE REQUIREMENTS
----------------------------------
All invoices must contain:
  (a) Unique invoice number (no duplicate invoice numbers accepted)
  (b) Vendor name exactly as stated in this agreement
  (c) ProcureSight purchase order number (where applicable)
  (d) Itemized line items with SKU, description, quantity, and unit price
  (e) Invoice date and payment due date
  (f) Currency and total amount due

Invoices not meeting these requirements will be returned unpaid without penalty
to ProcureSight for the resulting payment delay.

ARTICLE 6 — RENEWAL & TERMINATION
------------------------------------
Renewal : {renewal.capitalize()}.
Termination for Convenience : Either party may terminate this agreement with
  60 days written notice.
Termination for Cause : Either party may terminate immediately upon material
  breach if the breach is not cured within 15 days of written notice.

ARTICLE 7 — COMPLIANCE & AUDIT
--------------------------------
Vendor agrees to maintain records supporting all invoiced charges for a minimum
of 7 years. ProcureSight reserves the right to audit Vendor's invoices and
supporting documentation once per calendar year with 10 business days notice.

ARTICLE 8 — GOVERNING LAW
---------------------------
This agreement is governed by the laws of the State of California.

ARTICLE 9 — ENTIRE AGREEMENT
------------------------------
This document, together with any attached schedules, constitutes the entire
agreement between the parties with respect to its subject matter.

________________________________        ________________________________
Authorized Signatory, ProcureSight      Authorized Signatory, {vendor.name}
Date: ___________________________       Date: ___________________________
"""
    return content


# ── Policy generation ─────────────────────────────────────────────────────────

POLICY_TEMPLATES = [

    ("procurement_policy_general.md", """# Procurement Policy — General Guidelines
**Document ID:** PP-001
**Version:** 3.2
**Effective Date:** {effective_date}
**Owner:** Finance & Operations

---

## 1. Purpose

This policy establishes the rules and procedures governing the procurement of
goods and services at ProcureSight Corp. It ensures fiscal responsibility,
competitive sourcing, and compliance with applicable regulations.

## 2. Scope

Applies to all employees, contractors, and agents who authorize, request, or
process procurement activities on behalf of ProcureSight Corp.

## 3. Approval Thresholds

| Purchase Amount         | Approval Required            |
|-------------------------|------------------------------|
| Up to $500              | Department Manager           |
| $501 – $5,000           | Director of Finance          |
| $5,001 – $25,000        | VP of Finance                |
| $25,001 – $100,000      | CFO + VP of Finance          |
| Above $100,000          | Board Approval Required      |

All approvals must be documented in the procurement system before a purchase
order is issued.

## 4. Preferred Vendor Program

ProcureSight maintains a Preferred Vendor List (PVL). Procurement from vendors
on the PVL is encouraged and may be processed with expedited approval.

Purchases from non-PVL vendors exceeding $2,000 require a minimum of two (2)
competitive quotes or a documented sole-source justification.

## 5. Purchase Order Requirement

A valid Purchase Order (PO) is required for all purchases exceeding $1,000.
Emergency purchases may proceed without a PO, but must be ratified within 48
hours through the standard approval process.

## 6. Invoice Handling Procedure

1. Vendor submits invoice to **accounts.payable@procuresight.com**
2. AP team validates invoice against PO and receiving report (three-way match)
3. Discrepancies are returned to vendor within 5 business days
4. Approved invoices are processed for payment per contract terms
5. All invoices are retained for 7 years per records retention policy

## 7. Duplicate Invoice Policy

The AP system automatically flags invoices with duplicate invoice numbers.
Suspected duplicate payments must be:
- Placed on hold pending vendor confirmation
- Escalated to the Controller within 24 hours
- Documented in the duplicate payment log

## 8. Prohibited Purchases

The following purchases are prohibited without Board approval:
- Real estate transactions
- Equity investments
- Loans or financial guarantees to third parties
- Purchases from related parties without conflict-of-interest disclosure

## 9. Compliance

Violations of this policy must be reported to compliance@procuresight.com.
Non-compliance may result in disciplinary action up to and including termination.
"""),

    ("procurement_policy_reimbursements.md", """# Procurement Policy — Employee Reimbursements
**Document ID:** PP-002
**Version:** 2.1
**Effective Date:** {effective_date}
**Owner:** Finance & Operations

---

## 1. Purpose

This policy governs reimbursement of business expenses incurred by employees.

## 2. Eligible Expenses

Employees may be reimbursed for:
- Business travel (airfare, hotel, ground transport)
- Client entertainment (meals, events)
- Office supplies purchased on behalf of the company
- Professional development (courses, certifications, conferences)
- Telecommunications (phone, internet for remote workers)

## 3. Reimbursement Limits

| Category                     | Per-Event Limit      | Annual Limit    |
|------------------------------|----------------------|-----------------|
| Domestic Travel (per day)    | $350 (hotel + meals) | No annual cap   |
| Client Entertainment         | $150 per person      | $3,000 / year   |
| Office Supplies              | $100 per purchase    | $500 / year     |
| Professional Development     | $2,500 per course    | $5,000 / year   |

## 4. Receipts & Documentation

- Original receipts (or digital equivalents) are required for all expenses $25+
- Receipts must show: vendor name, date, items purchased, and amount
- Credit card statements alone are NOT acceptable documentation

## 5. Submission Deadlines

Expense reports must be submitted within 30 days of the expense date.
Late submissions require VP Finance approval and may be denied.

## 6. Processing Timeline

Approved expense reports are reimbursed via payroll within 2 pay cycles
of approval, or via ACH within 5 business days for amounts exceeding $500.

## 7. Non-Reimbursable Expenses

- Personal meals (not related to business activity)
- Alcohol above $25 per event
- Traffic and parking fines
- Personal subscriptions or entertainment
- Purchases not pre-approved when pre-approval is required
"""),

    ("procurement_policy_vendor_management.md", """# Procurement Policy — Vendor Management
**Document ID:** PP-003
**Version:** 1.4
**Effective Date:** {effective_date}
**Owner:** Finance & Operations

---

## 1. Preferred Vendor Selection Criteria

All new vendors must be evaluated against the following criteria before
being added to the Preferred Vendor List:

- Financial stability (credit check and references required for contracts > $50K)
- Insurance requirements (minimum $1M general liability)
- GDPR / data processing compliance (for any vendor accessing personal data)
- Ethical sourcing and labor practices attestation
- Pricing competitiveness (at least one comparable quote required)

## 2. Vendor Onboarding

New vendors must submit:
1. W-9 or equivalent tax form (non-US vendors: W-8BEN-E)
2. Proof of business registration
3. Banking details for ACH setup
4. Signed Vendor Code of Conduct

Vendor data is stored in the Vendor Master and maintained by Accounts Payable.

## 3. Annual Vendor Review

All vendors with annual spend exceeding $25,000 are subject to an annual review:
- Performance scorecard (on-time delivery, quality, responsiveness)
- Contract renewal assessment
- Pricing benchmark against market rates

Underperforming vendors may be placed on a Performance Improvement Plan (PIP)
or removed from the Preferred Vendor List.

## 4. Vendor Naming Standards

To prevent duplicate vendor records, all vendors must be registered using the
**legal business name** exactly as it appears on their W-9/W-8BEN-E.

Invoices received under alternate vendor names must be reconciled against the
Vendor Master before payment. Unrecognized vendor names trigger an automatic
hold and vendor verification workflow.

## 5. Single-Vendor Spend Concentration

No single vendor should represent more than 40% of total category spend.
Exceptions require CFO approval and documentation of the business justification.

## 6. Conflicts of Interest

Employees must disclose any personal, family, or financial relationship with
a vendor. Employees with undisclosed conflicts are subject to disciplinary action.

## 7. Vendor Payment Terms

Standard payment terms are Net 30. Variations from standard terms require
Finance Director approval and must be documented in the vendor contract.
Early payment discounts (e.g., 2/10 Net 30) are encouraged where available.
"""),

    ("procurement_policy_compliance.md", """# Procurement Policy — Compliance & Invoice Controls
**Document ID:** PP-004
**Version:** 1.0
**Effective Date:** {effective_date}
**Owner:** Finance & Compliance

---

## 1. Three-Way Match Requirement

All invoices for goods (not services) must be validated via three-way match:
1. Purchase Order (PO) — approved quantity and price
2. Goods Receipt — confirmed delivery
3. Vendor Invoice — amounts and items must reconcile

Discrepancies exceeding $50 or 2% of invoice value (whichever is lower) must
be resolved with the vendor before payment is released.

## 2. Segregation of Duties

- The employee who requisitions a purchase may NOT approve the same purchase
- The employee who approves an invoice may NOT also process the payment
- AP personnel may not create new vendors in the Vendor Master

## 3. Anomaly Detection Controls

The AP system applies automated controls to detect:
- Duplicate invoice numbers (same vendor, same number)
- Invoices with amounts ±20% outside vendor's 12-month average
- Invoices submitted on weekends or holidays
- Round-dollar invoices (potential estimate vs. actual)
- Invoices with mismatched tax amounts

Flagged invoices require manual review before payment.

## 4. Currency Controls

- USD is the default payment currency
- EUR payments require approval from Director of Finance
- JPY payments require CFO approval
- Payments in any other currency require Board approval

## 5. Records Retention

All procurement records (POs, invoices, approvals, contracts) must be retained
for a minimum of **7 years** from the payment date, in compliance with IRS
record-keeping requirements and applicable state laws.

## 6. Fraud Prevention

If an employee suspects procurement fraud, they must report immediately to:
- Their direct manager
- compliance@procuresight.com
- The anonymous hotline: 1-800-XXX-XXXX

Retaliation against good-faith reporters is strictly prohibited and subject
to immediate disciplinary action.
"""),

    ("procurement_policy_it_hardware.md", """# Procurement Policy — IT Hardware & Software
**Document ID:** PP-005
**Version:** 2.0
**Effective Date:** {effective_date}
**Owner:** IT & Finance

---

## 1. Purpose

This policy governs the procurement of IT hardware, software licenses, and
cloud services to ensure security, compatibility, and cost control.

## 2. Standard Equipment

All employees receive a standard equipment package upon hire:
- Laptop (business grade, 16GB RAM minimum)
- Monitor (24" or larger)
- Keyboard and mouse
- Headset (for remote/hybrid employees)

Standard equipment is procured centrally by IT from approved vendors.
Employees may not purchase personal equipment and seek reimbursement for
standard items.

## 3. Non-Standard Equipment

Non-standard equipment (standing desks, ergonomic peripherals, ultrawide
monitors) requires manager approval up to $500, Director approval above $500.

## 4. Software Procurement

All new software subscriptions must be reviewed by IT for:
- Security and data handling compliance
- Compatibility with existing systems
- License type and terms (per-seat, enterprise, etc.)
- Redundancy with existing tools

SaaS subscriptions over $1,000/year require IT security review before approval.

## 5. Asset Tracking

All hardware assets with a unit value above $200 must be registered in the
IT Asset Management system upon receipt. Asset tags must be applied immediately.

## 6. Disposal

Hardware disposal must follow the IT Asset Disposal Policy (PP-006).
Unauthorized disposal or personal retention of company equipment is prohibited.

## 7. Cloud Services

Cloud service agreements must be reviewed by Legal for data residency,
SLA, and termination provisions before execution. All cloud vendor contracts
must be registered in the contract management system.
"""),
]


def generate_policy(template: tuple[str, str], effective_date: date) -> tuple[str, str]:
    filename, content = template
    return filename, content.format(effective_date=effective_date.isoformat())


# ── main ─────────────────────────────────────────────────────────────────────

def generate(
    contracts_dir: Path = CONTRACTS_OUT,
    policies_dir: Path = POLICIES_OUT,
    sample_contracts_dir: Path = SAMPLE_CONTRACTS,
    sample_policies_dir: Path = SAMPLE_POLICIES,
    seed: int = SEED,
    verbose: bool = True,
) -> None:
    seed_all(seed)
    rng = random.Random(seed + 7)

    today = date.today()
    history_start = today - timedelta(days=548)  # ~18 months ago

    contracts_dir.mkdir(parents=True, exist_ok=True)
    policies_dir.mkdir(parents=True, exist_ok=True)
    sample_contracts_dir.mkdir(parents=True, exist_ok=True)
    sample_policies_dir.mkdir(parents=True, exist_ok=True)

    # ── Contracts: one per vendor ─────────────────────────────────────────────
    contract_count = 0
    for vi, vendor in enumerate(VENDOR_CATALOG):
        contract_no = f"VSA-{today.year}-{vi+1:03d}"
        start_delta = rng.randint(0, 365)
        start_date = history_start + timedelta(days=start_delta)

        content = generate_contract(vendor, contract_no, rng, start_date)
        safe_name = vendor.name.replace(" ", "_").replace("/", "_").replace("&", "and").lower()

        txt_path = contracts_dir / f"{safe_name}_contract.txt"
        txt_path.write_text(content, encoding="utf-8")

        contract_count += 1

    # Write 3 sample contracts
    for vi, vendor in enumerate(VENDOR_CATALOG[:3]):
        contract_no = f"VSA-SAMPLE-{vi+1:03d}"
        content = generate_contract(vendor, contract_no, rng, history_start)
        safe_name = vendor.name.replace(" ", "_").replace("/", "_").replace("&", "and").lower()
        (sample_contracts_dir / f"{safe_name}_contract.txt").write_text(content, encoding="utf-8")

    if verbose:
        print(f"  Wrote {contract_count} contracts (.txt) → {contracts_dir}")
        print(f"  Wrote 3 sample contracts → {sample_contracts_dir}")

    # ── Policies ──────────────────────────────────────────────────────────────
    policy_count = 0
    effective_date = history_start + timedelta(days=30)

    for template in POLICY_TEMPLATES:
        filename, content = generate_policy(template, effective_date)
        (policies_dir / filename).write_text(content, encoding="utf-8")
        policy_count += 1

    # Write 2 sample policies
    for template in POLICY_TEMPLATES[:2]:
        filename, content = generate_policy(template, effective_date)
        (sample_policies_dir / filename).write_text(content, encoding="utf-8")

    if verbose:
        print(f"  Wrote {policy_count} procurement policies → {policies_dir}")
        print(f"  Wrote 2 sample policies → {sample_policies_dir}")


if __name__ == "__main__":
    print("Generating contracts and policies...")
    generate(verbose=True)
    print("Done.")
