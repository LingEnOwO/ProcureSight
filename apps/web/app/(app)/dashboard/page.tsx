import { serverGet } from "@/lib/serverApiClient";
import { asObject, extractItems, pickString, type UnknownRecord } from "@/lib/dataHelpers";

export const dynamic = "force-dynamic";

function pickIdLike(obj: UnknownRecord): string {
  return pickString(obj, ["id", "invoice_id", "vendor_id", "uuid"], { numberToString: true });
}

function pickTitleLike(obj: UnknownRecord): string {
  return pickString(obj, ["name", "vendor_name", "invoice_no", "invoice_number", "title", "filename"]);
}

export default async function Page() {
  const [vendorsData, invoicesData] = await Promise.all([
    serverGet("/vendors").catch(() => null),
    serverGet("/invoices").catch(() => null),
  ]);

  const vendorsError = !vendorsData;
  const invoicesError = !invoicesData;

  const vendorsItems = extractItems(vendorsData);
  const invoicesItems = extractItems(invoicesData);

  const vendorCount = vendorsItems.length;
  const invoiceCount = invoicesItems.length;

  const recentVendors = vendorsItems.slice(0, 5).map(asObject);
  const recentInvoices = invoicesItems.slice(0, 5).map(asObject);

  const hasAnyError = Boolean(vendorsError || invoicesError);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-subtitle">Overview of your procurement activity</p>
      </div>

      {/* KPI cards */}
      <div className="kpi-grid">
        <a href="/vendors" className="kpi-card" aria-label="Go to Vendors">
          <div
            className="kpi-icon"
            style={{ background: "#eff6ff", color: "#2563eb" }}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <circle cx="6.5" cy="5.5" r="2.75" stroke="currentColor" strokeWidth="1.5" />
              <path
                d="M1 15c0-3 2.46-5 5.5-5s5.5 2 5.5 5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
              <circle cx="13.5" cy="5.5" r="2" stroke="currentColor" strokeWidth="1.25" opacity="0.5" />
              <path
                d="M16 15c0-2-1.2-3.2-2.5-3.75"
                stroke="currentColor"
                strokeWidth="1.25"
                strokeLinecap="round"
                opacity="0.5"
              />
            </svg>
          </div>
          <div className="kpi-label">Total Vendors</div>
          <div className="kpi-value">{vendorCount}</div>
          <div className="kpi-footer">
            View all vendors
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M2.5 6h7M7 3.5L9.5 6 7 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </a>

        <a href="/invoices" className="kpi-card" aria-label="Go to Invoices">
          <div
            className="kpi-icon"
            style={{ background: "#faf5ff", color: "#9333ea" }}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <rect x="2.5" y="1.5" width="13" height="15" rx="1.75" stroke="currentColor" strokeWidth="1.5" />
              <path
                d="M6 6.5h6M6 9.5h6M6 12.5h4"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
          </div>
          <div className="kpi-label">Total Invoices</div>
          <div className="kpi-value">{invoiceCount}</div>
          <div className="kpi-footer">
            View all invoices
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M2.5 6h7M7 3.5L9.5 6 7 8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </a>
      </div>

      {/* Error banner */}
      {hasAnyError && (
        <div className="alert-banner error">
          <div className="alert-title">Some data failed to load</div>
          <div style={{ fontSize: "0.8125rem", opacity: 0.85 }}>
            This may occur while the backend is starting up or endpoints are still being configured.
          </div>
        </div>
      )}

      {/* Recent lists */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
          gap: "1rem",
        }}
      >
        {/* Recent Vendors */}
        <div className="card">
          <div className="card-body">
            <div className="section-header">
              <span className="section-title">Recent Vendors</span>
              <a href="/vendors" className="section-link">
                View all
              </a>
            </div>
            {recentVendors.length === 0 ? (
              <div
                style={{
                  fontSize: "0.8125rem",
                  color: "var(--text-muted)",
                  padding: "0.75rem 0",
                }}
              >
                No vendors yet.
              </div>
            ) : (
              <div>
                {recentVendors.map((v, idx) => {
                  const id = pickIdLike(v);
                  const label = pickTitleLike(v) || id || `Vendor #${idx + 1}`;
                  const initial = label[0]?.toUpperCase() ?? "V";
                  return (
                    <div
                      key={`${id || idx}`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.625rem",
                        padding: "0.5rem 0",
                        borderBottom:
                          idx < recentVendors.length - 1
                            ? "1px solid var(--border-muted)"
                            : "none",
                      }}
                    >
                      <div className="vendor-avatar">{initial}</div>
                      <span style={{ fontSize: "0.875rem" }}>{label}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Recent Invoices */}
        <div className="card">
          <div className="card-body">
            <div className="section-header">
              <span className="section-title">Recent Invoices</span>
              <a href="/invoices" className="section-link">
                View all
              </a>
            </div>
            {recentInvoices.length === 0 ? (
              <div
                style={{
                  fontSize: "0.8125rem",
                  color: "var(--text-muted)",
                  padding: "0.75rem 0",
                }}
              >
                No invoices yet.
              </div>
            ) : (
              <div>
                {recentInvoices.map((inv, idx) => {
                  const id = pickIdLike(inv);
                  const label =
                    pickTitleLike(inv) || id || `Invoice #${idx + 1}`;
                  return (
                    <div
                      key={`${id || idx}`}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "0.5rem 0",
                        borderBottom:
                          idx < recentInvoices.length - 1
                            ? "1px solid var(--border-muted)"
                            : "none",
                      }}
                    >
                      <span style={{ fontSize: "0.875rem" }}>{label}</span>
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 14 14"
                        fill="none"
                        style={{ color: "var(--text-muted)", flexShrink: 0 }}
                      >
                        <path
                          d="M3 7h8M8.5 4.5L11 7l-2.5 2.5"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
