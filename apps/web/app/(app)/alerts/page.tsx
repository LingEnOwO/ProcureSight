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

function SeverityBadge({ severity }: { severity: string }) {
  if (!severity || severity === "—")
    return <span style={{ color: "var(--text-muted)" }}>—</span>;
  const s = severity.toLowerCase();
  let cls = "badge badge-gray";
  if (s === "critical" || s === "high") cls = "badge badge-red";
  else if (s === "medium") cls = "badge badge-orange";
  else if (s === "low") cls = "badge badge-yellow";
  return <span className={cls}>{severity}</span>;
}

function StatusBadge({ status }: { status: string }) {
  if (!status || status === "—")
    return <span style={{ color: "var(--text-muted)" }}>—</span>;
  const s = status.toLowerCase();
  let cls = "badge badge-blue";
  if (s === "open" || s === "active") cls = "badge badge-blue";
  else if (s === "resolved") cls = "badge badge-green";
  else if (s === "dismissed" || s === "acknowledged") cls = "badge badge-gray";
  return <span className={cls}>{status}</span>;
}

export default async function Page() {
  const response = await serverFetch("/alerts/");
  const data = await response.json();

  const raw = data as unknown;
  const items =
    asArray(asObject(raw).items).length > 0
      ? asArray(asObject(raw).items)
      : asArray(raw);

  const alerts = items.map(asObject);

  return (
    <div>
      <div className="page-header">
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.625rem" }}>
          <h1 className="page-title">Alerts</h1>
          <span
            style={{
              fontSize: "0.8125rem",
              color: "var(--text-muted)",
              fontWeight: 500,
            }}
          >
            {alerts.length} total
          </span>
        </div>
        <p className="page-subtitle">
          Anomaly detections and spend deviation alerts
        </p>
      </div>

      {alerts.length === 0 ? (
        <div className="table-wrapper">
          <div className="empty-state">
            <div className="empty-icon">
              <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
                <path
                  d="M11 2C8 2 5 4.5 5 8v4L3 14h16l-2-2V8c0-3.5-3-6-6-6z"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinejoin="round"
                />
                <path
                  d="M8.5 17a2.5 2.5 0 005 0"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <div className="empty-title">No alerts</div>
            <p className="empty-desc">
              Once the anomaly detection pipeline runs, alerts will appear here.
            </p>
          </div>
        </div>
      ) : (
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Alert Type</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Created</th>
                <th>Invoice Ref</th>
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

                const isResolved =
                  status.toLowerCase() === "resolved" ||
                  status.toLowerCase() === "dismissed" ||
                  status.toLowerCase() === "acknowledged";

                return (
                  <tr
                    key={id}
                    style={{ opacity: isResolved ? 0.65 : 1 }}
                  >
                    <td>
                      <span style={{ fontWeight: 600 }}>{alertType}</span>
                    </td>
                    <td>
                      <SeverityBadge severity={severity} />
                    </td>
                    <td>
                      <StatusBadge status={status} />
                    </td>
                    <td
                      style={{
                        color: "var(--text-muted)",
                        fontFamily: "monospace",
                        fontSize: "0.8125rem",
                      }}
                    >
                      {createdAt}
                    </td>
                    <td>
                      <span
                        style={{
                          fontFamily: "monospace",
                          fontSize: "0.8125rem",
                          color: "var(--text-secondary)",
                        }}
                      >
                        {invoiceRef}
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
