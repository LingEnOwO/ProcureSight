import { serverFetch } from "@/lib/serverApiClient";

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
  return typeof v === "number"
    ? v.toFixed(2)
    : typeof v === "string"
      ? v
      : "";
}

function pickVendorIdLike(obj: UnknownRecord): string {
  const v = obj.vendor_id ?? obj.vendorId;
  return typeof v === "string" ? v : typeof v === "number" ? String(v) : "";
}

function pickInvoiceDateLike(obj: UnknownRecord): string {
  const v = obj.invoice_date ?? obj.invoiceDate;
  return typeof v === "string" ? v : "";
}

function StatusBadge({ status }: { status: string }) {
  if (!status || status === "—") return <span style={{ color: "var(--text-muted)" }}>—</span>;
  const s = status.toLowerCase();
  let cls = "badge badge-gray";
  if (s === "paid") cls = "badge badge-green";
  else if (s === "pending") cls = "badge badge-yellow";
  else if (s === "overdue") cls = "badge badge-red";
  else if (s === "processing") cls = "badge badge-blue";
  else if (s === "cancelled" || s === "canceled") cls = "badge badge-gray";
  return <span className={cls}>{status}</span>;
}

export default async function Page() {
  const response = await serverFetch("/invoices");
  const data = await response.json();

  const raw = data as unknown;
  const items =
    asArray(asObject(raw).items).length > 0
      ? asArray(asObject(raw).items)
      : asArray(raw);

  const invoices = items.map(asObject);

  return (
    <div>
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.625rem" }}>
          <h1 className="page-title">Invoices</h1>
          <span
            style={{
              fontSize: "0.8125rem",
              color: "var(--text-muted)",
              fontWeight: 500,
            }}
          >
            {invoices.length} total
          </span>
        </div>
        <p className="page-subtitle">All ingested invoices and their details</p>
      </div>

      {invoices.length === 0 ? (
        <div className="table-wrapper">
          <div className="empty-state">
            <div className="empty-icon">
              <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
                <rect x="2" y="1" width="14" height="18" rx="2" stroke="currentColor" strokeWidth="1.5" />
                <path
                  d="M6 7h8M6 10.5h8M6 14h5"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <div className="empty-title">No invoices yet</div>
            <p className="empty-desc">
              Once you ingest documents, invoices will appear here.
            </p>
          </div>
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Invoice #</th>
                <th>Status</th>
                <th>Total</th>
                <th>Currency</th>
                <th>Invoice Date</th>
                <th>Vendor ID</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv, idx) => {
                const id = pickIdLike(inv) || String(idx);
                const invoiceNo =
                  pickInvoiceNoLike(inv) ||
                  pickIdLike(inv) ||
                  `Invoice #${idx + 1}`;
                const status = pickStatusLike(inv) || "—";
                const total = pickTotalLike(inv) || "—";
                const currency = pickCurrencyLike(inv) || "—";
                const invoiceDate = pickInvoiceDateLike(inv) || "—";
                const vendorId = pickVendorIdLike(inv) || "—";

                return (
                  <tr key={id}>
                    <td>
                      <span style={{ fontWeight: 600, fontFamily: "monospace", fontSize: "0.8125rem" }}>
                        {invoiceNo}
                      </span>
                    </td>
                    <td>
                      <StatusBadge status={status} />
                    </td>
                    <td>
                      {total !== "—" ? (
                        <span style={{ fontWeight: 600 }}>{total}</span>
                      ) : (
                        <span style={{ color: "var(--text-muted)" }}>—</span>
                      )}
                    </td>
                    <td>
                      <span style={{ color: total !== "—" ? "var(--text-secondary)" : "var(--text-muted)" }}>
                        {currency}
                      </span>
                    </td>
                    <td style={{ color: "var(--text-secondary)" }}>
                      {invoiceDate}
                    </td>
                    <td>
                      <span
                        style={{
                          fontFamily: "monospace",
                          fontSize: "0.8125rem",
                          color: "var(--text-muted)",
                        }}
                      >
                        {vendorId}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
