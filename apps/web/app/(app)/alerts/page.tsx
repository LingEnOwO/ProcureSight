import { serverFetch } from "@/lib/serverApiClient";
import { asObject, extractItems } from "@/lib/dataHelpers";
import AlertsTable from "./AlertsTable";

export const dynamic = "force-dynamic";

export default async function Page() {
  const response = await serverFetch("/alerts/");
  const data = await response.json();

  const alerts = extractItems(data).map(asObject);

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
