# Data Dictionary (v0)
## invoices_csv/*.csv
- invoice_no (string) – unique per vendor; ex: INV-1042
- vendor (string) – supplier name; ex: Apex Office Supply
- date (date, ISO) – ex: 2025-09-01
- currency (string, ISO 4217) – ex: USD
- subtotal (decimal) – ex: 1200.00
- tax (decimal) – ex: 96.00
- total (decimal) – ex: 1296.00 (≈ subtotal + tax)
## invoice_lines (embedded in JSON or separate CSV)
- sku (string) – ex: PPR-A4-500
- desc (string) – ex: Copy Paper A4 500 sheets
- qty (number) – ex: 10
- unit_price (decimal) – ex: 5.99
- line_total (decimal) – ex: 59.90 (≈ qty * unit_price)