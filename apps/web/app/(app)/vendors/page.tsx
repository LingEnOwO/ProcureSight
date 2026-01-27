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
  const v = obj.id ?? obj.vendor_id ?? obj.uuid;
  return typeof v === "string" ? v : typeof v === "number" ? String(v) : "";
}

function pickNameLike(obj: UnknownRecord): string {
  const v = obj.name ?? obj.vendor_name ?? obj.legal_name ?? obj.display_name;
  return typeof v === "string" ? v : "";
}

function pickEmailLike(obj: UnknownRecord): string {
  const v = obj.email ?? obj.contact_email;
  return typeof v === "string" ? v : "";
}

function pickPhoneLike(obj: UnknownRecord): string {
  const v = obj.phone ?? obj.contact_phone;
  return typeof v === "string" ? v : "";
}

function pickCreatedAtLike(obj: UnknownRecord): string {
  const v = obj.created_at ?? obj.createdAt;
  return typeof v === "string" ? v : "";
}

export default async function Page() {
  const title = "Vendors";

  const { data, error, response } = await api.GET("/vendors");

  const raw = data as unknown;
  const items =
    asArray(raw).length > 0 ? asArray(raw) : asArray(asObject(raw).items);

  const vendors = items.map(asObject);

  return (
    <main style={{ padding: 24 }}>
      <header style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0 }}>{title}</h1>
          <span style={{ fontSize: 13, opacity: 0.7 }}>
            {error ? "" : `${vendors.length} total`}
          </span>
        </div>
        <div style={{ fontSize: 13, opacity: 0.75, marginTop: 6 }}>
          Data source: <code>GET /vendors</code> (HTTP {response.status})
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
            Failed to load vendors
          </div>
          <pre style={{ marginTop: 10, whiteSpace: "pre-wrap", fontSize: 12 }}>
            {JSON.stringify(error, null, 2)}
          </pre>
          <div style={{ marginTop: 10, fontSize: 12, opacity: 0.85 }}>
            Check that the backend is running and <code>NEXT_PUBLIC_API_URL</code> is
            correct.
          </div>
        </section>
      ) : vendors.length === 0 ? (
        <section
          style={{
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            padding: 14,
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 6 }}>No vendors yet</div>
          <div style={{ fontSize: 13, opacity: 0.75 }}>
            Once you add vendors (or ingest invoices), they will appear here.
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
                  Name
                </th>
                <th style={{ textAlign: "left", padding: 12, fontSize: 12, opacity: 0.75 }}>
                  Email
                </th>
                <th style={{ textAlign: "left", padding: 12, fontSize: 12, opacity: 0.75 }}>
                  Phone
                </th>
                <th style={{ textAlign: "left", padding: 12, fontSize: 12, opacity: 0.75 }}>
                  Created
                </th>
              </tr>
            </thead>
            <tbody>
              {vendors.map((v, idx) => {
                const id = pickIdLike(v) || String(idx);
                const name = pickNameLike(v) || pickIdLike(v) || `Vendor #${idx + 1}`;
                const email = pickEmailLike(v);
                const phone = pickPhoneLike(v);
                const createdAt = pickCreatedAtLike(v);

                return (
                  <tr key={id} style={{ borderTop: "1px solid #e5e7eb" }}>
                    <td style={{ padding: 12, fontSize: 13, fontWeight: 600 }}>{name}</td>
                    <td style={{ padding: 12, fontSize: 13 }}>{email || "—"}</td>
                    <td style={{ padding: 12, fontSize: 13 }}>{phone || "—"}</td>
                    <td style={{ padding: 12, fontSize: 13 }}>{createdAt || "—"}</td>
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
