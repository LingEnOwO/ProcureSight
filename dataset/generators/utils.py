"""
Shared utilities, vendor catalog, and pricing helpers for ProcureSight dataset generation.
All randomness is seeded for reproducibility.
"""
from __future__ import annotations
import random
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

def seed_all(seed: int = 42) -> None:
    random.seed(seed)
    np.random.seed(seed)


# ---------------------------------------------------------------------------
# Product catalog item
# ---------------------------------------------------------------------------

@dataclass
class Product:
    sku_prefix: str
    desc: str
    unit_price_mean: float
    unit_price_std: float
    qty_mean: float
    qty_std: float
    qty_is_int: bool = True
    nullable_sku_prob: float = 0.05  # probability SKU is null for this product


@dataclass
class VendorProfile:
    name: str
    category: str
    currency: str
    products: list[Product]
    invoice_cadence: str          # "weekly" | "biweekly" | "monthly" | "bimonthly" | "quarterly" | "asneeded"
    cadence_jitter_days: int      # ± days of random jitter around cadence
    tax_rate: float
    payment_terms_days: int
    alternate_names: list[str]    # for naming-variation anomalies
    # invoices_per_period: vendor may submit multiple invoices per cadence cycle
    # (e.g., separate POs per department, or weekly billing batches)
    invoices_per_period_min: int = 1
    invoices_per_period_max: int = 1
    notes: str = ""


# ---------------------------------------------------------------------------
# Full vendor catalog  (30 vendors across 8 categories)
# ---------------------------------------------------------------------------

VENDOR_CATALOG: list[VendorProfile] = [

    # ── OFFICE SUPPLIES ──────────────────────────────────────────────────────

    VendorProfile(
        name="Apex Office Supply",
        category="office_supplies",
        currency="USD",
        invoice_cadence="biweekly",
        cadence_jitter_days=2,
        tax_rate=0.08,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=3,
        alternate_names=["Apex Office Supplies", "Apex Office Supply Co.", "APEX OFFICE SUPPLY"],
        products=[
            Product("AOS-PPR", "Copy Paper (Case, 10 Reams)", 42.50, 2.00, 5, 2),
            Product("AOS-TNR", "Black Laser Toner Cartridge", 89.99, 5.00, 2, 1),
            Product("AOS-PEN", "Ballpoint Pens (Box of 12)", 8.75, 0.50, 4, 2),
            Product("AOS-STK", "Sticky Notes Variety Pack", 12.99, 1.00, 3, 2),
            Product("AOS-FLD", "Hanging File Folders (25-pack)", 19.49, 1.50, 2, 1),
            Product("AOS-MRK", "Dry-Erase Markers Set", 14.25, 0.75, 2, 1),
            Product("AOS-CBN", "3-Ring Binders (Case of 12)", 55.00, 3.00, 1, 1),
            Product("AOS-COF", "Premium Ground Coffee (5 lb bag)", 34.99, 2.00, 3, 1),
        ],
    ),

    VendorProfile(
        name="Stationery World Inc.",
        category="office_supplies",
        currency="USD",
        invoice_cadence="biweekly",
        cadence_jitter_days=3,
        tax_rate=0.08,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=2,
        alternate_names=["Stationery World", "Stationery World Incorporated"],
        products=[
            Product("SWI-ENV", "Standard #10 Envelopes (500-pack)", 28.50, 2.00, 2, 1),
            Product("SWI-LBL", "Shipping Labels (100-pack)", 16.99, 1.00, 3, 1),
            Product("SWI-CLR", "Color Printer Ink Set (4-pack)", 67.99, 4.00, 2, 1),
            Product("SWI-NTB", "Spiral Notebooks (12-pack)", 24.99, 1.50, 2, 1),
            Product("SWI-TAP", "Packing Tape Rolls (6-pack)", 19.25, 1.00, 2, 1),
            Product("SWI-STA", "Heavy-Duty Stapler", 22.49, 2.00, 1, 1),
            Product("SWI-SSS", "Box of Staples (5000-count)", 6.99, 0.50, 3, 1),
            Product("SWI-WHT", "Whiteboard Cleaner Spray", 9.49, 0.50, 2, 1),
        ],
    ),

    VendorProfile(
        name="BlueSky Office Products",
        category="office_supplies",
        currency="USD",
        invoice_cadence="bimonthly",
        cadence_jitter_days=7,
        tax_rate=0.08,
        payment_terms_days=45,
        alternate_names=["Blue Sky Office Products", "BlueSky Office"],
        products=[
            Product("BSO-CHR", "Ergonomic Mesh Office Chair", 249.00, 20.00, 1, 1),
            Product("BSO-DSK", "Standing Desk Converter", 199.00, 15.00, 1, 1),
            Product("BSO-LMP", "LED Desk Lamp", 44.99, 3.00, 2, 1),
            Product("BSO-FRS", "Under-Desk Footrest", 34.99, 2.00, 2, 1),
            Product("BSO-MNT", "Monitor Arm (Single)", 89.00, 5.00, 1, 1),
        ],
    ),

    # ── IT HARDWARE ───────────────────────────────────────────────────────────

    VendorProfile(
        name="Cedar Industrial Tools",
        category="it_hardware",
        currency="USD",
        invoice_cadence="quarterly",
        cadence_jitter_days=10,
        tax_rate=0.08,
        payment_terms_days=60,
        alternate_names=["Cedar Industrial", "Cedar Tools Inc.", "Cedar Industrial Tools LLC"],
        products=[
            Product("CIT-MON", "27\" 4K IPS Monitor", 549.00, 30.00, 2, 2),
            Product("CIT-KBD", "Mechanical Keyboard (TKL)", 129.99, 10.00, 3, 2),
            Product("CIT-MSE", "Wireless Ergonomic Mouse", 69.99, 5.00, 3, 2),
            Product("CIT-HUB", "USB-C 10-Port Docking Station", 159.00, 10.00, 2, 1),
            Product("CIT-CBL", "Cat6 Ethernet Cable 25ft", 14.99, 1.00, 10, 5, True, 0.20),
            Product("CIT-SRG", "8-Outlet Surge Protector", 39.99, 3.00, 4, 2),
            Product("CIT-WEB", "1080p USB Webcam", 79.99, 5.00, 2, 1),
            Product("CIT-MIC", "USB Condenser Microphone", 89.99, 8.00, 1, 1),
        ],
    ),

    VendorProfile(
        name="TechStream Distributors",
        category="it_hardware",
        currency="USD",
        invoice_cadence="quarterly",
        cadence_jitter_days=14,
        tax_rate=0.08,
        payment_terms_days=60,
        alternate_names=["TechStream", "Tech Stream Distributors"],
        products=[
            Product("TSD-LPT", "Business Laptop 15\" (Core i7, 16GB)", 1249.00, 75.00, 2, 2),
            Product("TSD-TBT", "Business Tablet (10\", 64GB)", 449.00, 30.00, 1, 1),
            Product("TSD-SSD", "1TB NVMe SSD", 119.99, 8.00, 4, 2),
            Product("TSD-RAM", "32GB DDR5 RAM Kit", 159.99, 10.00, 2, 2),
            Product("TSD-SWT", "24-Port Gigabit Managed Switch", 299.00, 20.00, 1, 1),
            Product("TSD-RTR", "Business WiFi 6 Router", 249.00, 15.00, 1, 1),
            Product("TSD-NAS", "4-Bay NAS Enclosure", 399.00, 25.00, 1, 1),
            Product("TSD-UPS", "1500VA UPS Battery Backup", 229.00, 15.00, 1, 1),
        ],
    ),

    VendorProfile(
        name="Orion Electronics Supply",
        category="it_hardware",
        currency="USD",
        invoice_cadence="bimonthly",
        cadence_jitter_days=7,
        tax_rate=0.08,
        payment_terms_days=45,
        alternate_names=["Orion Electronics", "Orion Supply"],
        products=[
            Product("OES-HDM", "HDMI 2.1 Cable 6ft", 12.99, 1.00, 8, 3),
            Product("OES-USR", "USB-A to USB-C Adapter (3-pack)", 9.99, 0.50, 6, 2),
            Product("OES-PWR", "65W GaN USB-C Charger", 39.99, 3.00, 4, 2),
            Product("OES-BAT", "AA Batteries (48-pack)", 18.99, 1.00, 3, 1),
            Product("OES-LBL", "Label Printer", 79.00, 5.00, 1, 1),
            Product("OES-SCN", "Portable Document Scanner", 189.00, 12.00, 1, 1),
        ],
    ),

    # ── SAAS / SOFTWARE ───────────────────────────────────────────────────────

    VendorProfile(
        name="Nexus Cloud Solutions",
        category="saas_software",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=2,
        tax_rate=0.00,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=2,
        alternate_names=["Nexus Cloud", "Nexus Cloud Solutions Inc."],
        products=[
            Product("NCS-CRM", "CRM Platform — Monthly License (per seat)", 85.00, 3.00, 12, 3, False, 0.0),
            Product("NCS-STG", "Cloud Storage Add-on (1TB)", 25.00, 0.00, 5, 2, False, 0.0),
            Product("NCS-SPT", "Priority Support Plan", 199.00, 0.00, 1, 0, False, 0.0),
            Product("NCS-API", "API Overage (1M calls)", 49.00, 5.00, 2, 1, False, 0.0),
        ],
    ),

    VendorProfile(
        name="Dataflow Analytics Corp",
        category="saas_software",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=2,
        tax_rate=0.00,
        payment_terms_days=30,
        alternate_names=["Dataflow Analytics", "DataFlow Corp"],
        products=[
            Product("DAC-BSC", "Analytics Platform — Business Tier (monthly)", 450.00, 0.00, 1, 0, False, 0.0),
            Product("DAC-USR", "Additional User Seats (5-pack)", 175.00, 0.00, 2, 1, False, 0.0),
            Product("DAC-EXP", "Data Export API — Monthly", 99.00, 0.00, 1, 0, False, 0.0),
            Product("DAC-INT", "Integration Connector (per connector)", 49.00, 5.00, 3, 1, False, 0.0),
        ],
    ),

    VendorProfile(
        name="SecureEdge Cybersecurity",
        category="saas_software",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=3,
        tax_rate=0.00,
        payment_terms_days=30,
        alternate_names=["SecureEdge", "Secure Edge Cybersecurity LLC"],
        products=[
            Product("SEC-EPP", "Endpoint Protection (per device/month)", 8.50, 0.50, 25, 5, False, 0.0),
            Product("SEC-VPN", "Business VPN — Monthly (per user)", 6.00, 0.25, 15, 3, False, 0.0),
            Product("SEC-SOC", "Managed SOC Service — Monthly", 799.00, 0.00, 1, 0, False, 0.0),
            Product("SEC-PHI", "Phishing Simulation Training (per user/month)", 4.50, 0.25, 20, 5, False, 0.0),
            Product("SEC-PEN", "Quarterly Penetration Test", 1500.00, 100.00, 1, 0, False, 0.0),
        ],
    ),

    VendorProfile(
        name="ProjSync Software",
        category="saas_software",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=2,
        tax_rate=0.00,
        payment_terms_days=30,
        alternate_names=["ProjSync", "Proj Sync Software"],
        products=[
            Product("PSW-PRO", "Project Management — Pro Plan (monthly)", 299.00, 0.00, 1, 0, False, 0.0),
            Product("PSW-USR", "Additional Users (per user/month)", 12.00, 0.00, 10, 5, False, 0.0),
            Product("PSW-GAN", "Gantt Chart Add-on", 49.00, 0.00, 1, 0, False, 0.0),
        ],
    ),

    # ── LOGISTICS / SHIPPING ──────────────────────────────────────────────────

    VendorProfile(
        name="SwiftRoute Logistics",
        category="logistics_shipping",
        currency="USD",
        invoice_cadence="weekly",
        cadence_jitter_days=2,
        tax_rate=0.00,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=4,
        alternate_names=["SwiftRoute", "Swift Route Logistics LLC"],
        products=[
            Product("SRL-GND", "Ground Freight — Standard Pallet (per pallet)", 145.00, 20.00, 3, 2, False, 0.15),
            Product("SRL-EXP", "Express Air Freight (per shipment)", 289.00, 40.00, 2, 1, False, 0.10),
            Product("SRL-FUL", "Fulfillment Storage Fee (per pallet/month)", 45.00, 5.00, 10, 5, False, 0.20),
            Product("SRL-PKG", "Custom Packaging & Labeling (per order)", 18.50, 2.00, 5, 3, False, 0.25),
            Product("SRL-RTN", "Return Logistics Processing (per unit)", 8.75, 1.00, 12, 5, False, 0.20),
        ],
    ),

    VendorProfile(
        name="Meridian Freight Partners",
        category="logistics_shipping",
        currency="USD",
        invoice_cadence="biweekly",
        cadence_jitter_days=3,
        tax_rate=0.00,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=3,
        alternate_names=["Meridian Freight", "Meridian Partners"],
        products=[
            Product("MFP-LTL", "LTL Freight (per cwt)", 62.00, 8.00, 15, 5, False, 0.30),
            Product("MFP-FTL", "Full Truckload (per mile)", 3.20, 0.30, 250, 50, False, 0.10),
            Product("MFP-HZM", "Hazmat Handling Surcharge (flat)", 175.00, 10.00, 1, 0, False, 0.0),
            Product("MFP-INS", "Cargo Insurance (% declared value)", 0.85, 0.05, 1200, 300, False, 0.20),
            Product("MFP-FUE", "Fuel Surcharge (flat per shipment)", 38.00, 5.00, 4, 2, False, 0.20),
        ],
    ),

    VendorProfile(
        name="EuroShip GmbH",
        category="logistics_shipping",
        currency="EUR",
        invoice_cadence="biweekly",
        cadence_jitter_days=4,
        tax_rate=0.19,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=3,
        alternate_names=["EuroShip", "Euro Ship GmbH"],
        products=[
            Product("ESG-STD", "EU Standard Parcel Delivery (per parcel)", 12.50, 1.50, 20, 8, False, 0.20),
            Product("ESG-EXP", "EU Express Delivery (per parcel)", 28.00, 3.00, 8, 3, False, 0.15),
            Product("ESG-PLT", "EU Pallet Freight (per pallet)", 95.00, 10.00, 3, 1, False, 0.15),
            Product("ESG-CST", "Customs Clearance Fee (per shipment)", 65.00, 5.00, 2, 1, False, 0.20),
        ],
    ),

    # ── MANUFACTURING MATERIALS ───────────────────────────────────────────────

    VendorProfile(
        name="Pacific Metals & Alloys",
        category="manufacturing_materials",
        currency="USD",
        invoice_cadence="biweekly",
        cadence_jitter_days=4,
        tax_rate=0.08,
        payment_terms_days=45,
        invoices_per_period_min=1,
        invoices_per_period_max=3,
        alternate_names=["Pacific Metals", "Pacific Metals and Alloys Inc."],
        products=[
            Product("PMA-STL", "Cold-Rolled Steel Sheet 4x8 (per sheet)", 68.00, 8.00, 20, 10),
            Product("PMA-ALM", "Aluminum Bar Stock 1\" x 6ft (per piece)", 22.50, 2.50, 30, 10),
            Product("PMA-COP", "Copper Pipe 1/2\" x 10ft (per piece)", 18.75, 2.00, 15, 5),
            Product("PMA-GRD", "Steel Grinding Discs (25-pack)", 34.99, 2.00, 4, 2),
            Product("PMA-WLD", "MIG Welding Wire 10lb Spool", 49.99, 3.00, 3, 1),
            Product("PMA-BLT", "Hex Bolts M10x50mm (box of 100)", 19.99, 1.00, 5, 2),
        ],
    ),

    VendorProfile(
        name="Greenfield Polymers",
        category="manufacturing_materials",
        currency="USD",
        invoice_cadence="biweekly",
        cadence_jitter_days=5,
        tax_rate=0.08,
        payment_terms_days=45,
        invoices_per_period_min=1,
        invoices_per_period_max=2,
        alternate_names=["Greenfield Polymer", "Greenfield Polymers Inc."],
        products=[
            Product("GFP-ABS", "ABS Plastic Pellets (25 kg bag)", 58.00, 5.00, 10, 4),
            Product("GFP-PET", "PET Resin Granules (25 kg bag)", 45.00, 4.00, 10, 4),
            Product("GFP-SIL", "Industrial Silicone Compound (5L)", 89.99, 6.00, 4, 2),
            Product("GFP-EPX", "Epoxy Resin Kit 2L (resin + hardener)", 64.99, 5.00, 3, 1),
            Product("GFP-FOM", "Rigid Polyurethane Foam Sheets (4-pack)", 39.99, 3.00, 3, 1),
        ],
    ),

    VendorProfile(
        name="Nippon Industrial Materials",
        category="manufacturing_materials",
        currency="JPY",
        invoice_cadence="quarterly",
        cadence_jitter_days=14,
        tax_rate=0.10,
        payment_terms_days=60,
        alternate_names=["Nippon Industrial", "Nippon Materials"],
        products=[
            Product("NIM-SUS", "SUS304 Stainless Sheet 1.5mm (per sqm)", 4200.0, 300.0, 15, 5),
            Product("NIM-PRS", "Precision Bearings 6205 (per unit)", 850.0, 50.0, 20, 8),
            Product("NIM-SPR", "Industrial Spring Assortment Kit", 6500.0, 400.0, 2, 1),
            Product("NIM-SLT", "Cutting Oil (20L drum)", 8900.0, 500.0, 2, 1),
            Product("NIM-GKT", "Neoprene Gasket Sheet 500x500mm", 2100.0, 150.0, 5, 2),
        ],
    ),

    # ── CLEANING SERVICES ─────────────────────────────────────────────────────

    VendorProfile(
        name="BrightSpace Facility Services",
        category="cleaning_services",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=3,
        tax_rate=0.08,
        payment_terms_days=30,
        alternate_names=["BrightSpace Services", "Bright Space Facility Services"],
        products=[
            Product("BSF-CLN", "Daily Office Cleaning — Monthly Contract", 1200.00, 50.00, 1, 0, False, 0.0),
            Product("BSF-DPC", "Deep Clean Service (per session)", 480.00, 30.00, 1, 1),
            Product("BSF-CRP", "Carpet Steam Cleaning (per 1000 sqft)", 185.00, 15.00, 2, 1, False, 0.15),
            Product("BSF-WND", "Window Cleaning — Exterior (per floor)", 95.00, 10.00, 3, 1),
            Product("BSF-SUP", "Cleaning Supplies Replenishment (monthly)", 145.00, 10.00, 1, 0),
        ],
    ),

    VendorProfile(
        name="GreenClean Janitorial",
        category="cleaning_services",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=4,
        tax_rate=0.08,
        payment_terms_days=30,
        alternate_names=["GreenClean", "Green Clean Janitorial Services"],
        products=[
            Product("GCJ-SVC", "Weekly Janitorial Service (per week)", 320.00, 20.00, 4, 1, False, 0.0),
            Product("GCJ-RST", "Restroom Sanitization — Monthly", 240.00, 15.00, 1, 0, False, 0.0),
            Product("GCJ-PWR", "Pressure Washing — Parking Area (per session)", 350.00, 25.00, 1, 1),
            Product("GCJ-HND", "Hand Sanitizer Refill Stations (per unit)", 22.50, 2.00, 8, 3),
            Product("GCJ-DSP", "Touchless Soap Dispenser (per unit)", 34.99, 3.00, 4, 2),
        ],
    ),

    # ── CONSULTING ────────────────────────────────────────────────────────────

    VendorProfile(
        name="Vantage Strategy Group",
        category="consulting",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=10,
        tax_rate=0.00,
        payment_terms_days=30,
        alternate_names=["Vantage Strategy", "Vantage Group"],
        products=[
            Product("VSG-STR", "Strategic Advisory — Senior Partner (per hour)", 350.00, 25.00, 20, 10, False, 0.0),
            Product("VSG-ANL", "Business Analysis — Analyst (per hour)", 150.00, 15.00, 40, 15, False, 0.0),
            Product("VSG-WKS", "Executive Workshop Facilitation (per day)", 4500.00, 300.00, 1, 1, False, 0.0),
            Product("VSG-RPT", "Market Research Report (per deliverable)", 2800.00, 200.00, 1, 1, False, 0.10),
            Product("VSG-EXP", "Expense Reimbursement (travel/accommodation)", 620.00, 150.00, 1, 1, False, 0.30),
        ],
    ),

    VendorProfile(
        name="Turing Advisory Partners",
        category="consulting",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=7,
        tax_rate=0.00,
        payment_terms_days=30,
        alternate_names=["Turing Advisory", "Turing Partners"],
        products=[
            Product("TAP-DEV", "Software Engineering Consulting (per hour)", 185.00, 15.00, 60, 20, False, 0.0),
            Product("TAP-ARC", "Solution Architecture Review (per hour)", 225.00, 20.00, 20, 8, False, 0.0),
            Product("TAP-PMG", "Project Management Services (per hour)", 135.00, 10.00, 40, 15, False, 0.0),
            Product("TAP-TRN", "Technical Training Session (per day)", 2200.00, 150.00, 1, 1, False, 0.10),
            Product("TAP-EXP", "Expense Reimbursement", 480.00, 120.00, 1, 1, False, 0.35),
        ],
    ),

    VendorProfile(
        name="Meridian HR Consulting",
        category="consulting",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=5,
        tax_rate=0.00,
        payment_terms_days=30,
        alternate_names=["Meridian HR", "Meridian Human Resources Consulting"],
        products=[
            Product("MHR-REC", "Recruitment Services (per hire, % of salary)", 4200.00, 500.00, 1, 1, False, 0.15),
            Product("MHR-TRN", "HR Compliance Training (per session)", 1200.00, 100.00, 1, 1, False, 0.10),
            Product("MHR-PLY", "Payroll Processing Support (monthly)", 650.00, 50.00, 1, 0, False, 0.0),
            Product("MHR-ADV", "HR Policy Advisory (per hour)", 175.00, 15.00, 15, 5, False, 0.0),
        ],
    ),

    VendorProfile(
        name="Summit Legal & Compliance",
        category="consulting",
        currency="USD",
        invoice_cadence="asneeded",
        cadence_jitter_days=14,
        tax_rate=0.00,
        payment_terms_days=30,
        alternate_names=["Summit Legal", "Summit Legal Consulting"],
        products=[
            Product("SLC-ATT", "Attorney Services (per hour)", 395.00, 30.00, 12, 8, False, 0.0),
            Product("SLC-PAR", "Paralegal Research (per hour)", 145.00, 10.00, 20, 8, False, 0.0),
            Product("SLC-FLG", "Filing & Registration Fees (flat)", 350.00, 50.00, 1, 1, False, 0.20),
            Product("SLC-CTR", "Contract Review & Redline (per contract)", 950.00, 75.00, 1, 1, False, 0.10),
            Product("SLC-EXP", "Disbursements & Expenses", 280.00, 80.00, 1, 1, False, 0.35),
        ],
    ),

    # ── FACILITY MAINTENANCE ──────────────────────────────────────────────────

    VendorProfile(
        name="ProBuild Facility Solutions",
        category="facility_maintenance",
        currency="USD",
        invoice_cadence="asneeded",
        cadence_jitter_days=14,
        tax_rate=0.08,
        payment_terms_days=30,
        alternate_names=["ProBuild Solutions", "ProBuild Facility Services"],
        products=[
            Product("PBS-HVC", "HVAC Preventive Maintenance (per unit)", 285.00, 25.00, 2, 1),
            Product("PBS-ELC", "Electrical Repair — Labor (per hour)", 115.00, 10.00, 4, 2, False, 0.0),
            Product("PBS-PLM", "Plumbing Service — Labor (per hour)", 105.00, 10.00, 3, 2, False, 0.0),
            Product("PBS-PNT", "Interior Painting — Labor (per sqft)", 4.50, 0.50, 500, 200, False, 0.15),
            Product("PBS-MAT", "Building Materials — Miscellaneous", 180.00, 40.00, 1, 1, False, 0.30),
            Product("PBS-FLR", "Flooring Repair & Replacement (per sqft)", 8.75, 1.00, 150, 50, False, 0.20),
        ],
    ),

    VendorProfile(
        name="Vertex Fire & Safety",
        category="facility_maintenance",
        currency="USD",
        invoice_cadence="quarterly",
        cadence_jitter_days=10,
        tax_rate=0.08,
        payment_terms_days=30,
        alternate_names=["Vertex Fire Safety", "Vertex Fire and Safety"],
        products=[
            Product("VFS-EXT", "Fire Extinguisher Inspection (per unit)", 28.50, 2.00, 12, 4),
            Product("VFS-SPR", "Sprinkler System Inspection (per zone)", 185.00, 15.00, 3, 1),
            Product("VFS-ALM", "Smoke Alarm Testing & Certification (per floor)", 145.00, 10.00, 4, 1),
            Product("VFS-EXT2", "Fire Extinguisher Replacement (per unit)", 89.00, 5.00, 2, 1),
            Product("VFS-TRN", "Fire Safety Training Session", 450.00, 30.00, 1, 1),
        ],
    ),

    VendorProfile(
        name="AllGreen Landscaping",
        category="facility_maintenance",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=5,
        tax_rate=0.08,
        payment_terms_days=30,
        alternate_names=["All Green Landscaping", "AllGreen Landscape Services"],
        products=[
            Product("AGL-MNT", "Grounds Maintenance — Monthly", 680.00, 40.00, 1, 0, False, 0.0),
            Product("AGL-TRM", "Tree Trimming & Removal (per tree)", 220.00, 30.00, 2, 1),
            Product("AGL-IRG", "Irrigation System Maintenance (per session)", 175.00, 15.00, 1, 1),
            Product("AGL-MUL", "Mulch Installation (per cubic yard)", 45.00, 5.00, 8, 3),
            Product("AGL-SNW", "Snow Removal Service (per event)", 395.00, 30.00, 1, 1),
        ],
    ),

    VendorProfile(
        name="SafePath Elevator Services",
        category="facility_maintenance",
        currency="USD",
        invoice_cadence="quarterly",
        cadence_jitter_days=7,
        tax_rate=0.08,
        payment_terms_days=45,
        alternate_names=["SafePath Elevators", "Safe Path Elevator Services"],
        products=[
            Product("SPE-INS", "Elevator Quarterly Inspection", 550.00, 30.00, 1, 0, False, 0.0),
            Product("SPE-RPR", "Elevator Repair — Labor (per hour)", 195.00, 15.00, 4, 2, False, 0.0),
            Product("SPE-PRT", "Elevator Parts — Miscellaneous", 340.00, 80.00, 1, 1, False, 0.30),
            Product("SPE-EMG", "Emergency Call-Out Fee (flat)", 250.00, 0.00, 1, 0, False, 0.0),
        ],
    ),

    # ── ADDITIONAL VENDORS (to pad to 30+) ───────────────────────────────────

    VendorProfile(
        name="Cascade Catering Services",
        category="facility_maintenance",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=5,
        tax_rate=0.08,
        payment_terms_days=30,
        alternate_names=["Cascade Catering", "Cascade Food Services"],
        products=[
            Product("CCS-LCH", "Weekly Office Lunch Catering (per person)", 18.50, 2.00, 30, 10),
            Product("CCS-BRK", "Breakfast Meeting Setup (per person)", 12.75, 1.50, 20, 8),
            Product("CCS-EVT", "Corporate Event Catering (per person)", 65.00, 8.00, 40, 15),
            Product("CCS-COF", "Coffee & Beverage Service — Monthly", 480.00, 30.00, 1, 0, False, 0.0),
        ],
    ),

    VendorProfile(
        name="DataVault Backup Solutions",
        category="saas_software",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=2,
        tax_rate=0.00,
        payment_terms_days=30,
        alternate_names=["DataVault", "Data Vault Solutions"],
        products=[
            Product("DVB-STG", "Cloud Backup Storage (per TB/month)", 18.00, 1.00, 5, 2, False, 0.0),
            Product("DVB-RET", "Data Retention Extension (per TB/month)", 12.00, 1.00, 3, 1, False, 0.0),
            Product("DVB-RPT", "Disaster Recovery Test (per execution)", 149.00, 0.00, 1, 0, False, 0.0),
            Product("DVB-COM", "Compliance Reporting Add-on (monthly)", 99.00, 0.00, 1, 0, False, 0.0),
        ],
    ),

    VendorProfile(
        name="FleetWise Vehicle Services",
        category="logistics_shipping",
        currency="USD",
        invoice_cadence="biweekly",
        cadence_jitter_days=4,
        tax_rate=0.08,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=2,
        alternate_names=["FleetWise", "Fleet Wise Vehicle Services"],
        products=[
            Product("FWV-FUL", "Fleet Fuel Card — Monthly Statement", 1850.00, 200.00, 1, 0, False, 0.0),
            Product("FWV-OIL", "Oil Change & Fluid Check (per vehicle)", 65.00, 5.00, 4, 2),
            Product("FWV-TRE", "Tire Rotation & Balance (per vehicle)", 89.00, 8.00, 3, 1),
            Product("FWV-INS", "Fleet Insurance Installment", 1240.00, 50.00, 1, 0, False, 0.0),
            Product("FWV-REG", "Vehicle Registration & DMV Fees (per vehicle)", 185.00, 20.00, 2, 1),
        ],
    ),

    VendorProfile(
        name="Momentum Print & Design",
        category="office_supplies",
        currency="USD",
        invoice_cadence="asneeded",
        cadence_jitter_days=10,
        tax_rate=0.08,
        payment_terms_days=30,
        alternate_names=["Momentum Print", "Momentum Design & Print"],
        products=[
            Product("MPD-BCR", "Business Cards (500-pack, full color)", 89.00, 8.00, 2, 1),
            Product("MPD-BNR", "Vinyl Banner (per sqft)", 8.50, 0.75, 24, 8, False, 0.15),
            Product("MPD-BRO", "Tri-Fold Brochures (250-pack)", 125.00, 10.00, 2, 1),
            Product("MPD-STD", "Roll-Up Display Stand", 249.00, 20.00, 1, 1),
            Product("MPD-ENV", "Custom Printed Envelopes (250-pack)", 78.00, 6.00, 2, 1),
        ],
    ),

    VendorProfile(
        name="IronCore Security Systems",
        category="facility_maintenance",
        currency="USD",
        invoice_cadence="quarterly",
        cadence_jitter_days=10,
        tax_rate=0.08,
        payment_terms_days=45,
        alternate_names=["IronCore Security", "Iron Core Systems"],
        products=[
            Product("ISS-MON", "Security Monitoring Service — Monthly", 350.00, 0.00, 3, 0, False, 0.0),
            Product("ISS-CAM", "Security Camera — HD (per unit)", 189.00, 15.00, 2, 1),
            Product("ISS-KPD", "Access Control Keypad (per door)", 245.00, 20.00, 2, 1),
            Product("ISS-RPR", "Security System Repair — Labor (per hour)", 125.00, 10.00, 3, 1, False, 0.0),
            Product("ISS-AUD", "Annual Security Audit", 1200.00, 75.00, 1, 0, False, 0.0),
        ],
    ),

    # ── ADDITIONAL VENDORS (batch 2 — high volume) ───────────────────────────

    VendorProfile(
        name="Rapid Parts Express",
        category="manufacturing_materials",
        currency="USD",
        invoice_cadence="weekly",
        cadence_jitter_days=2,
        tax_rate=0.08,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=3,
        alternate_names=["Rapid Parts", "Rapid Parts Express Inc."],
        products=[
            Product("RPE-NUT", "Hex Nuts M8 (box of 200)", 14.99, 1.00, 5, 2),
            Product("RPE-SCR", "Machine Screws #10-32 (box of 100)", 11.49, 0.75, 6, 2),
            Product("RPE-WAS", "Flat Washers M8 (box of 200)", 8.99, 0.50, 6, 2),
            Product("RPE-RVT", "Pop Rivets 3/16\" (box of 100)", 12.49, 0.75, 4, 2),
            Product("RPE-ORI", "O-Ring Assortment Kit (250-piece)", 24.99, 2.00, 2, 1),
            Product("RPE-FLT", "Hydraulic Filter (per unit)", 34.99, 3.00, 3, 1),
            Product("RPE-SLV", "Aluminum Standoff Spacers (50-pack)", 18.99, 1.50, 3, 1),
        ],
    ),

    VendorProfile(
        name="CoreLab Scientific Supply",
        category="manufacturing_materials",
        currency="USD",
        invoice_cadence="biweekly",
        cadence_jitter_days=3,
        tax_rate=0.08,
        payment_terms_days=45,
        invoices_per_period_min=1,
        invoices_per_period_max=2,
        alternate_names=["CoreLab Supply", "Core Lab Scientific"],
        products=[
            Product("CLS-GNT", "Nitrile Gloves (box of 100)", 18.99, 1.50, 4, 2),
            Product("CLS-PPE", "Safety Goggles (per pair)", 12.49, 1.00, 6, 2),
            Product("CLS-EAR", "Disposable Earplugs (box of 200)", 19.99, 1.00, 2, 1),
            Product("CLS-LAB", "Lab Coat — White (per unit)", 29.99, 2.00, 3, 1),
            Product("CLS-MSK", "N95 Respirator Masks (box of 20)", 34.99, 2.00, 3, 1),
            Product("CLS-DIS", "Industrial Disinfectant 5L", 28.99, 2.00, 4, 2),
        ],
    ),

    VendorProfile(
        name="Summit Packaging Solutions",
        category="logistics_shipping",
        currency="USD",
        invoice_cadence="weekly",
        cadence_jitter_days=2,
        tax_rate=0.08,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=3,
        alternate_names=["Summit Packaging", "Summit Packaging Co."],
        products=[
            Product("SPS-BOX", "Corrugated Shipping Box 12x12x12 (25-pack)", 38.99, 3.00, 4, 2),
            Product("SPS-BUB", "Bubble Wrap Roll 12\" x 100ft", 22.49, 1.50, 3, 1),
            Product("SPS-TPE", "Kraft Paper Roll 12\" x 200ft", 17.99, 1.00, 3, 1),
            Product("SPS-ENV", "Poly Mailers 10x13 (100-pack)", 21.99, 1.50, 4, 2),
            Product("SPS-PLT", "Stretch Wrap Film 18\" x 1500ft", 34.99, 2.00, 2, 1),
            Product("SPS-LAB", "Direct Thermal Shipping Labels (500-pack)", 28.99, 2.00, 3, 1),
        ],
    ),

    VendorProfile(
        name="CloudPeak Infrastructure",
        category="saas_software",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=2,
        tax_rate=0.00,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=2,
        alternate_names=["CloudPeak", "Cloud Peak Infrastructure LLC"],
        products=[
            Product("CPI-CMP", "Cloud Compute — Standard Tier (per vCPU-hour)", 0.048, 0.002, 2000, 400, False, 0.0),
            Product("CPI-STG", "Object Storage (per GB/month)", 0.023, 0.001, 5000, 1000, False, 0.0),
            Product("CPI-NET", "Data Transfer Out (per GB)", 0.09, 0.005, 1000, 300, False, 0.0),
            Product("CPI-LDB", "Managed Load Balancer (per instance/month)", 18.00, 0.00, 3, 1, False, 0.0),
            Product("CPI-DNS", "Managed DNS (per hosted zone/month)", 0.50, 0.00, 5, 1, False, 0.0),
            Product("CPI-MON", "Infrastructure Monitoring (per host/month)", 15.00, 1.00, 20, 5, False, 0.0),
        ],
    ),

    VendorProfile(
        name="Brightwork Electrical Supply",
        category="facility_maintenance",
        currency="USD",
        invoice_cadence="biweekly",
        cadence_jitter_days=4,
        tax_rate=0.08,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=2,
        alternate_names=["Brightwork Electric", "Brightwork Electrical"],
        products=[
            Product("BWE-BRK", "Circuit Breaker 20A (per unit)", 18.99, 1.50, 4, 2),
            Product("BWE-WIR", "12 AWG Electrical Wire 250ft (spool)", 89.99, 5.00, 1, 1),
            Product("BWE-OUT", "Duplex Outlet (per unit)", 4.99, 0.25, 12, 4),
            Product("BWE-PNL", "LED Panel Light 2x4ft (per unit)", 44.99, 3.00, 4, 2),
            Product("BWE-EXT", "Heavy-Duty Extension Cord 25ft", 24.99, 1.50, 3, 1),
            Product("BWE-SWT", "Occupancy Sensor Switch (per unit)", 29.99, 2.00, 3, 1),
        ],
    ),

    VendorProfile(
        name="WestCoast HVAC Supplies",
        category="facility_maintenance",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=5,
        tax_rate=0.08,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=3,
        alternate_names=["WestCoast HVAC", "West Coast HVAC Supply"],
        products=[
            Product("WHS-FLT", "HVAC Air Filter MERV-13 20x20 (6-pack)", 54.99, 4.00, 2, 1),
            Product("WHS-BLT", "HVAC Belt (per unit)", 12.99, 1.00, 2, 1),
            Product("WHS-REF", "Refrigerant R-410A (30 lb cylinder)", 189.00, 15.00, 1, 1),
            Product("WHS-CAP", "Run Capacitor 45+5 MFD (per unit)", 24.99, 2.00, 2, 1),
            Product("WHS-TRM", "Digital Thermostat — Programmable", 69.99, 5.00, 2, 1),
            Product("WHS-COL", "Coil Cleaner Spray 19oz (4-pack)", 38.99, 2.00, 2, 1),
        ],
    ),

    VendorProfile(
        name="Apex Staffing Solutions",
        category="consulting",
        currency="USD",
        invoice_cadence="biweekly",
        cadence_jitter_days=3,
        tax_rate=0.00,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=2,
        alternate_names=["Apex Staffing", "Apex Staffing Solutions LLC"],
        products=[
            Product("ASS-TMP", "Temporary Staffing — Administrative (per hour)", 28.50, 2.00, 80, 20, False, 0.0),
            Product("ASS-SKL", "Skilled Contractor — IT (per hour)", 85.00, 8.00, 40, 15, False, 0.0),
            Product("ASS-MGT", "Managed Services — Team Lead (per hour)", 115.00, 10.00, 20, 8, False, 0.0),
            Product("ASS-ONB", "Onboarding & Screening Fee (per placement)", 350.00, 25.00, 1, 1, False, 0.10),
        ],
    ),

    VendorProfile(
        name="PrimeCare Occupational Health",
        category="consulting",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=5,
        tax_rate=0.00,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=1,
        alternate_names=["PrimeCare Health", "Prime Care Occupational"],
        products=[
            Product("PCO-DRG", "Pre-Employment Drug Screening (per test)", 45.00, 3.00, 5, 2, False, 0.15),
            Product("PCO-PHY", "Annual Physical Examination (per employee)", 125.00, 10.00, 8, 3, False, 0.10),
            Product("PCO-FLU", "Flu Vaccination Clinic (per dose)", 28.00, 2.00, 20, 8),
            Product("PCO-EAP", "Employee Assistance Program (per employee/month)", 4.50, 0.25, 50, 10, False, 0.0),
            Product("PCO-FST", "First Aid Training Session (per session)", 380.00, 25.00, 1, 1, False, 0.10),
        ],
    ),

    VendorProfile(
        name="GlobalLink Telecom",
        category="saas_software",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=2,
        tax_rate=0.07,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=1,
        alternate_names=["GlobalLink", "Global Link Telecom Inc."],
        products=[
            Product("GLT-VOI", "VoIP Business Lines (per line/month)", 22.00, 1.00, 20, 5, False, 0.0),
            Product("GLT-INT", "Dedicated Internet (100 Mbps, monthly)", 450.00, 0.00, 1, 0, False, 0.0),
            Product("GLT-CON", "Conference Call Bridge (per minute)", 0.03, 0.002, 5000, 1000, False, 0.0),
            Product("GLT-FAX", "eFax Service (per number/month)", 9.99, 0.00, 3, 1, False, 0.0),
            Product("GLT-SIP", "SIP Trunk (per channel/month)", 18.00, 1.00, 5, 2, False, 0.0),
        ],
    ),

    VendorProfile(
        name="ClearPath Waste Management",
        category="facility_maintenance",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=4,
        tax_rate=0.08,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=1,
        alternate_names=["ClearPath Waste", "Clear Path Waste Management"],
        products=[
            Product("CPW-GRB", "General Waste Pickup — Weekly (monthly)", 380.00, 20.00, 1, 0, False, 0.0),
            Product("CPW-RCY", "Recycling Pickup — Weekly (monthly)", 145.00, 10.00, 1, 0, False, 0.0),
            Product("CPW-SHR", "Document Shredding Service (per pickup)", 85.00, 5.00, 1, 1),
            Product("CPW-HAZ", "Hazardous Waste Disposal (per container)", 225.00, 20.00, 1, 1),
            Product("CPW-BIN", "Extra Waste Bin Rental (monthly)", 55.00, 3.00, 2, 1),
        ],
    ),

    VendorProfile(
        name="Integra Insurance Brokers",
        category="consulting",
        currency="USD",
        invoice_cadence="monthly",
        cadence_jitter_days=3,
        tax_rate=0.00,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=1,
        alternate_names=["Integra Insurance", "Integra Brokers"],
        products=[
            Product("IIB-GL",  "General Liability Premium (monthly installment)", 850.00, 30.00, 1, 0, False, 0.0),
            Product("IIB-PL",  "Professional Liability (E&O) — Monthly", 420.00, 20.00, 1, 0, False, 0.0),
            Product("IIB-CYB", "Cyber Liability Insurance — Monthly", 380.00, 25.00, 1, 0, False, 0.0),
            Product("IIB-WCM", "Workers Comp Premium — Monthly", 1250.00, 50.00, 1, 0, False, 0.0),
            Product("IIB-SVC", "Broker Advisory Fee (quarterly, billed monthly)", 250.00, 0.00, 1, 0, False, 0.0),
        ],
    ),

    VendorProfile(
        name="DirectBuy Industrial",
        category="manufacturing_materials",
        currency="USD",
        invoice_cadence="weekly",
        cadence_jitter_days=2,
        tax_rate=0.08,
        payment_terms_days=30,
        invoices_per_period_min=1,
        invoices_per_period_max=3,
        alternate_names=["Direct Buy Industrial", "DirectBuy Supply"],
        products=[
            Product("DBI-ABR", "Abrasive Sandpaper Sheets (50-pack)", 24.99, 2.00, 4, 2),
            Product("DBI-CLT", "Cutting Blade 14\" (per blade)", 18.99, 1.50, 3, 1),
            Product("DBI-LUB", "Multi-Purpose Lubricant 16oz (6-pack)", 29.99, 2.00, 3, 1),
            Product("DBI-TWR", "Shop Towels (roll of 60)", 12.99, 0.75, 6, 2),
            Product("DBI-GAL", "5-Gallon Bucket (per unit)", 7.49, 0.50, 8, 3),
            Product("DBI-STR", "Cable Tie Assortment (200-pack)", 14.99, 1.00, 4, 2),
            Product("DBI-MRK", "Paint Marker Industrial Set (8 colors)", 22.99, 1.50, 2, 1),
        ],
    ),

    VendorProfile(
        name="FastTrack Courier Services",
        category="logistics_shipping",
        currency="USD",
        invoice_cadence="weekly",
        cadence_jitter_days=1,
        tax_rate=0.00,
        payment_terms_days=15,
        invoices_per_period_min=2,
        invoices_per_period_max=5,
        alternate_names=["FastTrack Courier", "FastTrack Services"],
        products=[
            Product("FTC-SDA", "Same-Day Local Delivery (per package)", 24.99, 3.00, 5, 3, False, 0.25),
            Product("FTC-NXT", "Next-Day Air (per package)", 38.50, 4.00, 4, 2, False, 0.20),
            Product("FTC-GND", "Ground Delivery (per package)", 12.99, 1.50, 8, 4, False, 0.20),
            Product("FTC-LRG", "Oversized Package Surcharge (per package)", 18.00, 2.00, 2, 1, False, 0.30),
            Product("FTC-SIG", "Signature Required (per package)", 4.50, 0.25, 6, 3, False, 0.30),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def random_date_in_range(start: date, end: date, rng: random.Random) -> date:
    delta = (end - start).days
    return start + timedelta(days=rng.randint(0, delta))


def generate_invoice_dates(
    vendor: VendorProfile,
    history_start: date,
    history_end: date,
    rng: random.Random,
) -> list[date]:
    """Return a flat list of invoice dates for the vendor over the history window.

    If the vendor has invoices_per_period_max > 1, each cadence slot may produce
    multiple invoice dates (spread within a ±3 day window), simulating separate
    POs or department orders landing in the same billing period.
    """
    cadence_days = {
        "weekly": 7,
        "biweekly": 14,
        "monthly": 30,
        "bimonthly": 60,
        "quarterly": 91,
        "asneeded": None,
    }[vendor.invoice_cadence]

    dates: list[date] = []

    if cadence_days is None:
        count = rng.randint(2, 8)
        for _ in range(count):
            dates.append(random_date_in_range(history_start, history_end, rng))
        dates.sort()
        return dates

    current = history_start + timedelta(days=rng.randint(0, cadence_days))
    while current <= history_end:
        jitter = rng.randint(-vendor.cadence_jitter_days, vendor.cadence_jitter_days)
        base_date = current + timedelta(days=jitter)

        invoices_this_period = rng.randint(
            vendor.invoices_per_period_min,
            vendor.invoices_per_period_max,
        )
        for i in range(invoices_this_period):
            offset = rng.randint(-3, 3) if i > 0 else 0
            invoice_date = base_date + timedelta(days=offset)
            if history_start <= invoice_date <= history_end:
                dates.append(invoice_date)

        current += timedelta(days=cadence_days)

    dates.sort()
    return dates


# ---------------------------------------------------------------------------
# Invoice number generation
# ---------------------------------------------------------------------------

def make_invoice_no(vendor_idx: int, sequence: int, year: int, rng: random.Random) -> str:
    prefix = f"INV-{year}-V{vendor_idx:02d}"
    return f"{prefix}-{sequence:04d}"


# ---------------------------------------------------------------------------
# Price sampling (with optional spike injection)
# ---------------------------------------------------------------------------

def sample_price(product: Product, rng: random.Random, spike: bool = False) -> float:
    mean = product.unit_price_mean * (3.5 if spike else 1.0)
    val = rng.gauss(mean, product.unit_price_std)
    return max(round(val, 2), 0.01)


def sample_qty(product: Product, rng: random.Random, spike: bool = False) -> float:
    mean = product.qty_mean * (4.0 if spike else 1.0)
    val = rng.gauss(mean, product.qty_std)
    val = max(val, 1.0)
    if product.qty_is_int:
        return float(int(round(val)))
    return round(val, 2)


# ---------------------------------------------------------------------------
# Invoice assembly
# ---------------------------------------------------------------------------

def build_invoice(
    vendor: VendorProfile,
    invoice_date: date,
    invoice_no: str,
    rng: random.Random,
    num_lines: Optional[int] = None,
    null_due_date: bool = False,
) -> dict:
    """Assemble a single invoice dict matching the ProcureSight schema exactly."""

    if num_lines is None:
        num_lines = rng.randint(1, min(len(vendor.products), 8))

    products = rng.sample(vendor.products, k=min(num_lines, len(vendor.products)))

    lines = []
    for prod in products:
        qty = sample_qty(prod, rng)
        unit_price = sample_price(prod, rng)
        line_total = round(qty * unit_price, 2)

        sku: Optional[str] = None
        if prod.sku_prefix and rng.random() > prod.nullable_sku_prob:
            sku = prod.sku_prefix

        lines.append({
            "sku": sku,
            "desc": prod.desc,
            "qty": qty,
            "unit_price": unit_price,
            "line_total": line_total,
        })

    subtotal = round(sum(ln["line_total"] for ln in lines), 2)
    tax = round(subtotal * vendor.tax_rate, 2)
    total = round(subtotal + tax, 2)

    due_date: Optional[str] = None
    if not null_due_date:
        due = invoice_date + timedelta(days=vendor.payment_terms_days)
        due_date = due.isoformat()

    return {
        "invoice_no": invoice_no,
        "vendor": vendor.name,
        "invoice_date": invoice_date.isoformat(),
        "due_date": due_date,
        "currency": vendor.currency,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "lines": lines,
    }
