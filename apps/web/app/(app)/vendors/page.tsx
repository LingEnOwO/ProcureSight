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

function getInitials(name: string): string {
  return name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0] ?? "")
    .join("")
    .toUpperCase() || "V";
}

const AVATAR_COLORS = [
  { bg: "#eff6ff", color: "#2563eb" },
  { bg: "#faf5ff", color: "#9333ea" },
  { bg: "#f0fdf4", color: "#16a34a" },
  { bg: "#fff7ed", color: "#ea580c" },
  { bg: "#fef2f2", color: "#dc2626" },
  { bg: "#f0f9ff", color: "#0284c7" },
];

export default async function Page() {
  const response = await serverFetch("/vendors");
  const data = await response.json();

  const raw = data as unknown;
  const items =
    asArray(raw).length > 0 ? asArray(raw) : asArray(asObject(raw).items);

  const vendors = items.map(asObject);

  return (
    <div>
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.625rem" }}>
          <h1 className="page-title">Vendors</h1>
          <span
            style={{
              fontSize: "0.8125rem",
              color: "var(--text-muted)",
              fontWeight: 500,
            }}
          >
            {vendors.length} total
          </span>
        </div>
        <p className="page-subtitle">Vendor master data and contact information</p>
      </div>

      {vendors.length === 0 ? (
        <div className="table-wrapper">
          <div className="empty-state">
            <div className="empty-icon">
              <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
                <circle cx="8" cy="7" r="3.5" stroke="currentColor" strokeWidth="1.5" />
                <path
                  d="M1.5 19c0-3.5 3-5.5 6.5-5.5s6.5 2 6.5 5.5"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
                <circle cx="16.5" cy="7" r="2.5" stroke="currentColor" strokeWidth="1.25" opacity="0.5" />
                <path
                  d="M20.5 19c0-2-1.5-3.5-3-4"
                  stroke="currentColor"
                  strokeWidth="1.25"
                  strokeLinecap="round"
                  opacity="0.5"
                />
              </svg>
            </div>
            <div className="empty-title">No vendors yet</div>
            <p className="empty-desc">
              Once you add vendors or ingest invoices, they will appear here.
            </p>
          </div>
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Vendor</th>
                <th>Email</th>
                <th>Phone</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {vendors.map((v, idx) => {
                const id = pickIdLike(v) || String(idx);
                const name =
                  pickNameLike(v) || pickIdLike(v) || `Vendor #${idx + 1}`;
                const email = pickEmailLike(v);
                const phone = pickPhoneLike(v);
                const createdAt = pickCreatedAtLike(v);
                const initials = getInitials(name);
                const { bg, color } = AVATAR_COLORS[idx % AVATAR_COLORS.length];

                return (
                  <tr key={id}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.625rem" }}>
                        <div
                          style={{
                            width: 30,
                            height: 30,
                            borderRadius: "50%",
                            background: bg,
                            color: color,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            fontSize: "10px",
                            fontWeight: 700,
                            flexShrink: 0,
                          }}
                        >
                          {initials.slice(0, 2)}
                        </div>
                        <span style={{ fontWeight: 600 }}>{name}</span>
                      </div>
                    </td>
                    <td style={{ color: "var(--text-secondary)" }}>
                      {email || <span style={{ color: "var(--text-muted)" }}>—</span>}
                    </td>
                    <td style={{ color: "var(--text-secondary)" }}>
                      {phone || <span style={{ color: "var(--text-muted)" }}>—</span>}
                    </td>
                    <td
                      style={{
                        color: "var(--text-muted)",
                        fontFamily: "monospace",
                        fontSize: "0.8125rem",
                      }}
                    >
                      {createdAt || "—"}
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
