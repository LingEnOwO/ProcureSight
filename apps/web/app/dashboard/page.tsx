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
  const v = obj.id ?? obj.invoice_id ?? obj.vendor_id ?? obj.uuid;
  return typeof v === "string" ? v : typeof v === "number" ? String(v) : "";
}

function pickTitleLike(obj: UnknownRecord): string {
  const v =
    obj.name ??
    obj.vendor_name ??
    obj.invoice_no ??
    obj.invoice_number ??
    obj.title ??
    obj.filename;
  return typeof v === "string" ? v : "";
}

export default async function Page() {
  // Phase 3D-3 goal: show a real dashboard shell + prove we can fetch real domain data.
  // We DO NOT call every endpoint; we only pull a couple key collections.
  const [vendorsRes, invoicesRes] = await Promise.all([
    api.GET("/vendors"),
    api.GET("/invoices"),
  ]);

  const vendorsError = vendorsRes.error;
  const invoicesError = invoicesRes.error;

  const vendorsData = vendorsRes.data as unknown;
  const invoicesData = invoicesRes.data as unknown;

  // Many APIs return either an array or an object like { items: [...] }
  const vendorsItems =
    asArray(vendorsData).length > 0
      ? asArray(vendorsData)
      : asArray(asObject(vendorsData).items);

  const invoicesItems =
    asArray(invoicesData).length > 0
      ? asArray(invoicesData)
      : asArray(asObject(invoicesData).items);

  const vendorCount = vendorsItems.length;
  const invoiceCount = invoicesItems.length;

  const recentVendors = vendorsItems.slice(0, 5).map(asObject);
  const recentInvoices = invoicesItems.slice(0, 5).map(asObject);

  const hasAnyError = Boolean(vendorsError || invoicesError);

  return (
    <main style={{ padding: 24 }}>
      <header style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 6 }}>Dashboard</h1>
        <div style={{ fontSize: 13, opacity: 0.75 }}>
          Overview of vendors and invoices
        </div>
      </header>

      {/* KPI cards */}
      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <a
          href="/vendors"
          style={{
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            padding: 14,
            color: "inherit",
            textDecoration: "none",
            display: "block",
          }}
          aria-label="Go to Vendors"
        >
          <div style={{ fontSize: 12, opacity: 0.7 }}>Vendors</div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>{vendorCount}</div>
          <div style={{ fontSize: 12, opacity: 0.75, marginTop: 6 }}>View vendors</div>
        </a>
        <a
          href="/invoices"
          style={{
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            padding: 14,
            color: "inherit",
            textDecoration: "none",
            display: "block",
          }}
          aria-label="Go to Invoices"
        >
          <div style={{ fontSize: 12, opacity: 0.7 }}>Invoices</div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>{invoiceCount}</div>
          <div style={{ fontSize: 12, opacity: 0.75, marginTop: 6 }}>View invoices</div>
        </a>
      </section>

      {/* Errors */}
      {hasAnyError ? (
        <section style={{ border: "1px solid #fecaca", background: "#fff1f2", borderRadius: 12, padding: 14, marginBottom: 16 }}>
          <div style={{ fontWeight: 700, color: "#9f1239" }}>Some requests failed</div>
          <div style={{ fontSize: 12, opacity: 0.85, marginTop: 6 }}>
            This is expected while backend endpoints/auth are still in flux.
          </div>
          {vendorsError ? (
            <pre style={{ marginTop: 10, whiteSpace: "pre-wrap", fontSize: 12 }}>
              vendors error: {JSON.stringify(vendorsError, null, 2)}
            </pre>
          ) : null}
          {invoicesError ? (
            <pre style={{ marginTop: 10, whiteSpace: "pre-wrap", fontSize: 12 }}>
              invoices error: {JSON.stringify(invoicesError, null, 2)}
            </pre>
          ) : null}
        </section>
      ) : null}

      {/* Recent lists */}
      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 12,
        }}
      >
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 14 }}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Recent vendors</div>
          {recentVendors.length === 0 ? (
            <div style={{ fontSize: 13, opacity: 0.75 }}>No vendors found.</div>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {recentVendors.map((v, idx) => {
                const id = pickIdLike(v);
                const label = pickTitleLike(v) || id || `Vendor #${idx + 1}`;
                return (
                  <li key={`${id || idx}`} style={{ marginBottom: 6 }}>
                    <span style={{ fontSize: 13 }}>{label}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 14 }}>
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Recent invoices</div>
          {recentInvoices.length === 0 ? (
            <div style={{ fontSize: 13, opacity: 0.75 }}>No invoices found.</div>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {recentInvoices.map((inv, idx) => {
                const id = pickIdLike(inv);
                const label = pickTitleLike(inv) || id || `Invoice #${idx + 1}`;
                return (
                  <li key={`${id || idx}`} style={{ marginBottom: 6 }}>
                    <span style={{ fontSize: 13 }}>{label}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>

      {/* Debug (temporary)
      
      <details style={{ marginTop: 16 }}>
        <summary style={{ cursor: "pointer", fontSize: 13, opacity: 0.85 }}>
          Debug responses (temporary)
        </summary>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>vendors</div>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
              {JSON.stringify(vendorsData ?? null, null, 2)}
            </pre>
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>invoices</div>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
              {JSON.stringify(invoicesData ?? null, null, 2)}
            </pre>
          </div>
        </div>
      </details>
      */}
    </main>
  );
}
