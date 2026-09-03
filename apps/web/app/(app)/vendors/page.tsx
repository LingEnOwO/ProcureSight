import { serverFetch } from "@/lib/serverApiClient";
import { asObject, extractItems, pickString, type UnknownRecord } from "@/lib/dataHelpers";
import { EmptyState } from "@/components/EmptyState";

export const dynamic = "force-dynamic";

function pickIdLike(obj: UnknownRecord): string {
  return pickString(obj, ["id", "vendor_id", "uuid"], { numberToString: true });
}

function pickNameLike(obj: UnknownRecord): string {
  return pickString(obj, ["name", "vendor_name", "legal_name", "display_name"]);
}

function pickEmailLike(obj: UnknownRecord): string {
  return pickString(obj, ["email", "contact_email"]);
}

function pickPhoneLike(obj: UnknownRecord): string {
  return pickString(obj, ["phone", "contact_phone"]);
}

function pickCreatedAtLike(obj: UnknownRecord): string {
  return pickString(obj, ["created_at", "createdAt"]);
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

  const vendors = extractItems(data).map(asObject);

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
        <EmptyState
          icon={
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
          }
          title="No vendors yet"
          description="Once you add vendors or ingest invoices, they will appear here."
        />
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
