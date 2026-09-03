import { serverFetch } from "@/lib/serverApiClient";
import { asObject, extractItems, pickString, type UnknownRecord } from "@/lib/dataHelpers";
import { InvoiceStatusBadge } from "@/components/badges";
import { EmptyState } from "@/components/EmptyState";

export const dynamic = "force-dynamic";

function pickIdLike(obj: UnknownRecord): string {
  return pickString(obj, ["id", "invoice_id", "uuid"], { numberToString: true });
}

function pickInvoiceNoLike(obj: UnknownRecord): string {
  return pickString(obj, ["invoice_no", "invoice_number", "number"]);
}

function pickStatusLike(obj: UnknownRecord): string {
  return pickString(obj, ["status"]);
}

function pickCurrencyLike(obj: UnknownRecord): string {
  return pickString(obj, ["currency"]);
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
  return pickString(obj, ["vendor_id", "vendorId"], { numberToString: true });
}

function pickInvoiceDateLike(obj: UnknownRecord): string {
  return pickString(obj, ["invoice_date", "invoiceDate"]);
}

export default async function Page() {
  const response = await serverFetch("/invoices");
  const data = await response.json();

  const invoices = extractItems(data).map(asObject);

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
        <EmptyState
          icon={
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
              <rect x="2" y="1" width="14" height="18" rx="2" stroke="currentColor" strokeWidth="1.5" />
              <path
                d="M6 7h8M6 10.5h8M6 14h5"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
          }
          title="No invoices yet"
          description="Once you ingest documents, invoices will appear here."
        />
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
                      <InvoiceStatusBadge status={status} />
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
