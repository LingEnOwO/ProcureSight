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
  const v = obj.id ?? obj.alert_id ?? obj.uuid;
  return typeof v === "string" ? v : typeof v === "number" ? String(v) : "";
}

function pickAlertType(obj: UnknownRecord): string {
  const v = obj.alert_type ?? obj.type ?? obj.rule_name;
  return typeof v === "string" ? v : "—";
}

function pickSeverity(obj: UnknownRecord): string {
  const v = obj.severity;
  return typeof v === "string" ? v : "—";
}

function pickStatus(obj: UnknownRecord): string {
  const v = obj.status;
  return typeof v === "string" ? v : "—";
}

function pickCreatedAt(obj: UnknownRecord): string {
  const v = obj.created_at ?? obj.createdAt ?? obj.timestamp;
  return typeof v === "string" ? v : "—";
}

function pickInvoiceRef(obj: UnknownRecord): string {
  const v = obj.invoice_id ?? obj.invoiceId ?? obj.invoice_no;
  return typeof v === "string"
    ? v
    : typeof v === "number"
      ? String(v)
      : "—";
}

export default async function Page() {
  const title = "Alerts";

  const { data, error, response } = await api.GET("/alerts/", {});

  const raw = data as unknown;
  // Alerts might come back as { items, limit, offset } or just an array
  const items =
    asArray(asObject(raw).items).length > 0
      ? asArray(asObject(raw).items)
      : asArray(raw);

  const alerts = items.map(asObject);

  return (
    <main style={{ padding: 24 }}>
      <header style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0 }}>{title}</h1>
          <span style={{ fontSize: 13, opacity: 0.7 }}>
            {error ? "" : `${alerts.length} total`}
          </span>
        </div>
        <div style={{ fontSize: 13, opacity: 0.75, marginTop: 6 }}>
          Data source: <code>GET /alerts</code> (HTTP {response.status})
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
            Failed to load alerts
          </div>
          <pre style={{ marginTop: 10, whiteSpace: "pre-wrap", fontSize: 12 }}>
            {JSON.stringify(error, null, 2)}
          </pre>
          <div style={{ marginTop: 10, fontSize: 12, opacity: 0.85 }}>
            Check that the backend is running and the alerts router is
            registered in <code>main.py</code>.
          </div>
        </section>
      ) : alerts.length === 0 ? (
        <section
          style={{
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            padding: 14,
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 6 }}>No alerts yet</div>
          <div style={{ fontSize: 13, opacity: 0.75 }}>
            Once the anomaly detection pipeline runs, alerts will appear here.
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
                <th
                  style={{
                    textAlign: "left",
                    padding: 12,
                    fontSize: 12,
                    opacity: 0.75,
                  }}
                >
                  Alert Type
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: 12,
                    fontSize: 12,
                    opacity: 0.75,
                  }}
                >
                  Severity
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: 12,
                    fontSize: 12,
                    opacity: 0.75,
                  }}
                >
                  Status
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: 12,
                    fontSize: 12,
                    opacity: 0.75,
                  }}
                >
                  Created
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: 12,
                    fontSize: 12,
                    opacity: 0.75,
                  }}
                >
                  Invoice Ref
                </th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert, idx) => {
                const id = pickIdLike(alert) || String(idx);
                const alertType = pickAlertType(alert);
                const severity = pickSeverity(alert);
                const status = pickStatus(alert);
                const createdAt = pickCreatedAt(alert);
                const invoiceRef = pickInvoiceRef(alert);

                // Apply different styling based on severity
                let severityColor = "#6b7280"; // gray for default
                if (severity.toLowerCase() === "high") severityColor = "#dc2626"; // red
                else if (severity.toLowerCase() === "medium") severityColor = "#ea580c"; // orange
                else if (severity.toLowerCase() === "low") severityColor = "#ca8a04"; // yellow

                // Status styling
                const isResolved =
                  status.toLowerCase() === "resolved" ||
                  status.toLowerCase() === "dismissed" ||
                  status.toLowerCase() === "acknowledged";

                return (
                  <tr key={id} style={{ borderTop: "1px solid #e5e7eb" }}>
                    <td style={{ padding: 12, fontSize: 13, fontWeight: 600 }}>
                      {alertType}
                    </td>
                    <td
                      style={{
                        padding: 12,
                        fontSize: 13,
                        color: severityColor,
                        fontWeight: 600,
                      }}
                    >
                      {severity}
                    </td>
                    <td
                      style={{
                        padding: 12,
                        fontSize: 13,
                        opacity: isResolved ? 0.6 : 1,
                      }}
                    >
                      {status}
                    </td>
                    <td
                      style={{
                        padding: 12,
                        fontSize: 13,
                        fontFamily: "monospace",
                      }}
                    >
                      {createdAt}
                    </td>
                    <td style={{ padding: 12, fontSize: 13 }}>
                      {invoiceRef}
                    </td>
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
