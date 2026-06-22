"use client";

import { useState } from "react";
import { pickString, type UnknownRecord } from "@/lib/dataHelpers";
import { SeverityBadge, AlertStatusBadge } from "@/components/badges";
import { EmptyState } from "@/components/EmptyState";
import AlertDetailDrawer from "./AlertDetailDrawer";

function pickIdLike(obj: UnknownRecord): string {
  return pickString(obj, ["id", "alert_id", "uuid"], { numberToString: true });
}

function pickAlertType(obj: UnknownRecord): string {
  return pickString(obj, ["alert_type", "type", "rule_name"], { fallback: "—" });
}

function pickSeverity(obj: UnknownRecord): string {
  return pickString(obj, ["severity"], { fallback: "—" });
}

function pickStatus(obj: UnknownRecord): string {
  return pickString(obj, ["status"], { fallback: "—" });
}

function pickCreatedAt(obj: UnknownRecord): string {
  return pickString(obj, ["created_at", "createdAt", "timestamp"], { fallback: "—" });
}

function pickInvoiceRef(obj: UnknownRecord): string {
  return pickString(obj, ["invoice_id", "invoiceId", "invoice_no"], {
    numberToString: true,
    fallback: "—",
  });
}

interface AlertsTableProps {
  alerts: UnknownRecord[];
}

export default function AlertsTable({ alerts }: AlertsTableProps) {
  const [selectedAlert, setSelectedAlert] = useState<UnknownRecord | null>(null);

  if (alerts.length === 0) {
    return (
      <EmptyState
        icon={
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
        }
        title="No alerts"
        description="Once the anomaly detection pipeline runs, alerts will appear here."
      />
    );
  }

  return (
    <>
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
                  style={{ opacity: isResolved ? 0.65 : 1, cursor: "pointer" }}
                  onClick={() => setSelectedAlert(alert)}
                >
                  <td>
                    <span style={{ fontWeight: 600 }}>{alertType}</span>
                  </td>
                  <td>
                    <SeverityBadge severity={severity} />
                  </td>
                  <td>
                    <AlertStatusBadge status={status} />
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

      {selectedAlert && (
        <AlertDetailDrawer
          alert={selectedAlert}
          onClose={() => setSelectedAlert(null)}
        />
      )}
    </>
  );
}
