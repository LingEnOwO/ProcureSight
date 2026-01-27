import { api } from "@/lib/apiClient";

export const dynamic = "force-dynamic";

type UnknownRecord = Record<string, unknown>;

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asObject(value: unknown): UnknownRecord {
  return value && typeof value === "object" ? (value as UnknownRecord) : {};
}

function pickIdLike(obj: UnknownRecord): string {
  const v = obj.id ?? obj.invoice_id ?? obj.uuid;
  return typeof v === "string" ? v : typeof v === "number" ? String(v) : "";
}

function pickInvoiceNoLike(obj: UnknownRecord): string {
  const v = obj.invoice_no ?? obj.invoice_number ?? obj.number;
  return typeof v === "string" ? v : "";
}

function pickStatusLike(obj: UnknownRecord): string {
  const v = obj.status;
  return typeof v === "string" ? v : "";
}

function pickCurrencyLike(obj: UnknownRecord): string {
  const v = obj.currency;
  return typeof v === "string" ? v : "";
}

function pickTotalLike(obj: UnknownRecord): string {
  const v = obj.total ?? obj.amount_total;
  return typeof v === "number" ? v.toFixed(2) : typeof v === "string" ? v : "";
}

function pickVendorIdLike(obj: UnknownRecord): string {
  const v = obj.vendor_id ?? obj.vendorId;
  return typeof v === "string" ? v : typeof v === "number" ? String(v) : "";
}

function pickInvoiceDateLike(obj: UnknownRecord): string {
  const v = obj.invoice_date ?? obj.invoiceDate;
  return typeof v === "string" ? v : "";
}

export default async function Page() {
  const title = "Invoices";

  const { data, error, response } = await api.GET("/invoices");

  const raw = data as unknown;
  // invoices commonly come back as { items, limit, offset }
  const items =
    asArray(asObject(raw).items).length > 0
      ? asArray(asObject(raw).items)
      : asArray(raw);

  const invoices = items.map(asObject);

  return (
    <main style={{ padding: 24 }}>
      <header style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0 }}>{title}</h1>
          <span style={{ fontSize: 13, opacity: 0.7 }}>
            {error ? "" : `${invoices.length} total`}
          </span>
        </div>
        <div style={{ fontSize: 13, opacity: 0.75, marginTop: 6 }}>
          Data source: <code>GET /invoices</code> (HTTP {response.status})
        </div>
      </header>

      {error ? (
        <section
          style={{
            border: "1px solid #fecaca",
            background: "#fff1f2",
            borderRadius: 12,
            padding: 14,
          }}
        >
          <div style={{ fontWeight: 700, color: "#9f1239" }}>
            Failed to load invoices
          </div>
          <pre style={{ marginTop: 10, whiteSpace: "pre-wrap", fontSize: 12 }}>
            {JSON.stringify(error, null, 2)}
          </pre>
          <div style={{ marginTop: 10, fontSize: 12, opacity: 0.85 }}>
            Check that the backend is running and <code>NEXT_PUBLIC_API_URL</code> is
            correct.
          </div>
        </section>
      ) : invoices.length === 0 ? (
        <section
          style={{
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            padding: 14,
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 6 }}>No invoices yet</div>
          <div style={{ fontSize: 13, opacity: 0.75 }}>
            Once you ingest documents, invoices will appear here.
          </div>
        </section>
      ) : (
        <section
          style={{
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            overflow: "hidden",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#f9fafb" }}>
                <th style={{ textAlign: "left", padding: 12, fontSize: 12, opacity: 0.75 }}>
                  Invoice #
                </th>
                <th style={{ textAlign: "left", padding: 12, fontSize: 12, opacity: 0.75 }}>
                  Status
                </th>
                <th style={{ textAlign: "left", padding: 12, fontSize: 12, opacity: 0.75 }}>
                  Total
                </th>
                <th style={{ textAlign: "left", padding: 12, fontSize: 12, opacity: 0.75 }}>
                  Currency
                </th>
                <th style={{ textAlign: "left", padding: 12, fontSize: 12, opacity: 0.75 }}>
                  Invoice date
                </th>
                <th style={{ textAlign: "left", padding: 12, fontSize: 12, opacity: 0.75 }}>
                  Vendor ID
                </th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv, idx) => {
                const id = pickIdLike(inv) || String(idx);
                const invoiceNo = pickInvoiceNoLike(inv) || pickIdLike(inv) || `Invoice #${idx + 1}`;
                const status = pickStatusLike(inv) || "—";
                const total = pickTotalLike(inv) || "—";
                const currency = pickCurrencyLike(inv) || "—";
                const invoiceDate = pickInvoiceDateLike(inv) || "—";
                const vendorId = pickVendorIdLike(inv) || "—";

                return (
                  <tr key={id} style={{ borderTop: "1px solid #e5e7eb" }}>
                    <td style={{ padding: 12, fontSize: 13, fontWeight: 600 }}>{invoiceNo}</td>
                    <td style={{ padding: 12, fontSize: 13 }}>{status}</td>
                    <td style={{ padding: 12, fontSize: 13 }}>{total}</td>
                    <td style={{ padding: 12, fontSize: 13 }}>{currency}</td>
                    <td style={{ padding: 12, fontSize: 13 }}>{invoiceDate}</td>
                    <td style={{ padding: 12, fontSize: 13 }}>{vendorId}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {/*
        Debug helper (keep commented):
        <pre>{JSON.stringify(data ?? null, null, 2)}</pre>
      */}
    </main>
  );
}
