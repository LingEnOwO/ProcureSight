import { serverFetch } from "@/lib/serverApiClient";
import AlertsTable from "./AlertsTable";

export const dynamic = "force-dynamic";

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
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

      <AlertsTable alerts={alerts} />
    </div>
  );
}
