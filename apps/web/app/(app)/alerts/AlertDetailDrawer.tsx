"use client";

import { useCallback, useEffect, useState } from "react";
import { SeverityBadge, AlertStatusBadge } from "@/components/badges";

type UnknownRecord = Record<string, unknown>;

interface LlmOutput {
  summary: string;
  evidence: string[];
  why_it_matters: string;
  recommended_action: string;
  confidence: string;
  source?: string;
}

interface ExplanationData {
  alert_id: string;
  alert_type: string;
  severity: string | null;
  explanation: string;
  source: string;
  cached: boolean;
  llm_output: LlmOutput;
  evidence: {
    current_invoice: UnknownRecord;
    historical_examples: unknown[];
    metrics: UnknownRecord;
  };
}

type DrawerState =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "success"; data: ExplanationData };

interface Props {
  alert: UnknownRecord;
  onClose: () => void;
}

function MetaItem({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: "0.6875rem",
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--text-muted)",
          marginBottom: "0.125rem",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: "0.8125rem",
          color: "var(--text-secondary)",
          fontFamily: mono ? "monospace" : undefined,
        }}
      >
        {value}
      </div>
    </div>
  );
}

export default function AlertDetailDrawer({ alert, onClose }: Props) {
  const alertId =
    typeof alert.id === "string"
      ? alert.id
      : typeof alert.alert_id === "string"
        ? alert.alert_id
        : String(alert.id ?? "");

  const [state, setState] = useState<DrawerState>({ status: "loading" });

  const fetchExplanation = useCallback(
    async (signal: AbortSignal) => {
      setState({ status: "loading" });
      try {
        const res = await fetch(`/api/backend/alerts/${alertId}/explain`, {
          method: "POST",
          signal,
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(`Request failed (${res.status}): ${text}`);
        }
        const data: ExplanationData = await res.json();
        setState({ status: "success", data });
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setState({
          status: "error",
          error: err instanceof Error ? err.message : "Unknown error",
        });
      }
    },
    [alertId],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    fetchExplanation(ctrl.signal);
    return () => ctrl.abort();
  }, [fetchExplanation]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const alertType = String(alert.alert_type ?? alert.type ?? "—");
  const severity = String(alert.severity ?? "—");
  const status = String(alert.status ?? "—");
  const createdAt = String(alert.created_at ?? alert.createdAt ?? "—");
  const invoiceRef = String(alert.invoice_id ?? alert.invoice_no ?? "—");

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />

      <div className="drawer" role="dialog" aria-modal="true" aria-label="Alert detail">
        <div className="drawer-header">
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              gap: "1rem",
            }}
          >
            <div>
              <div
                style={{
                  fontWeight: 700,
                  fontSize: "1rem",
                  color: "var(--text-primary)",
                  marginBottom: "0.375rem",
                }}
              >
                {alertType}
              </div>
              <div
                style={{
                  display: "flex",
                  gap: "0.5rem",
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                <SeverityBadge severity={severity} />
                <AlertStatusBadge status={status} />
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="btn-secondary"
              style={{ flexShrink: 0, padding: "0.3rem 0.625rem" }}
              aria-label="Close"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path
                  d="M2 2l10 10M12 2L2 12"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>

          <div
            style={{
              marginTop: "0.75rem",
              display: "flex",
              flexWrap: "wrap",
              gap: "1.25rem",
            }}
          >
            <MetaItem label="Created" value={createdAt} mono />
            <MetaItem label="Invoice Ref" value={invoiceRef} mono />
            <MetaItem label="Alert ID" value={alertId} mono />
          </div>
        </div>

        <div className="drawer-body">
          {state.status === "loading" && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.625rem",
                padding: "1.5rem 0",
                color: "var(--text-muted)",
              }}
            >
              <span className="spinner" />
              <span style={{ fontSize: "0.875rem" }}>Generating explanation…</span>
            </div>
          )}

          {state.status === "error" && (
            <div className="alert-banner error">
              <div className="alert-title">Failed to load explanation</div>
              <div style={{ marginBottom: "0.75rem", fontSize: "0.8125rem" }}>
                {state.error}
              </div>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  const ctrl = new AbortController();
                  fetchExplanation(ctrl.signal);
                }}
              >
                Retry
              </button>
            </div>
          )}

          {state.status === "success" && (() => {
            const { data } = state;
            const lo = data.llm_output;
            const metrics = data.evidence?.metrics ?? {};
            const sourceIsTemplate = data.source === "template";

            return (
              <>
                <div style={{ marginBottom: "1rem", display: "flex", gap: "0.375rem", flexWrap: "wrap" }}>
                  <span className={`badge ${sourceIsTemplate ? "badge-gray" : "badge-purple"}`}>
                    {sourceIsTemplate ? "Template explanation" : "Generated by AI"}
                  </span>
                  {data.cached && (
                    <span className="badge badge-gray">Cached</span>
                  )}
                </div>

                <div className="drawer-section">
                  <div className="drawer-section-title">Alert Summary</div>
                  <p
                    style={{
                      fontSize: "0.875rem",
                      color: "var(--text-secondary)",
                      lineHeight: 1.6,
                    }}
                  >
                    {lo.summary}
                  </p>
                </div>

                <div className="drawer-section">
                  <div className="drawer-section-title">Why This Was Flagged</div>
                  <p
                    style={{
                      fontSize: "0.875rem",
                      color: "var(--text-secondary)",
                      lineHeight: 1.6,
                    }}
                  >
                    {lo.why_it_matters}
                  </p>
                </div>

                {(lo.evidence?.length > 0 || Object.keys(metrics).length > 0) && (
                  <div className="drawer-section">
                    <div className="drawer-section-title">Evidence</div>
                    {lo.evidence?.length > 0 && (
                      <ul
                        style={{
                          margin: "0 0 0.75rem 0",
                          paddingLeft: "1.25rem",
                        }}
                      >
                        {lo.evidence.map((item, i) => (
                          <li
                            key={i}
                            style={{
                              fontSize: "0.875rem",
                              color: "var(--text-secondary)",
                              marginBottom: "0.25rem",
                              lineHeight: 1.55,
                            }}
                          >
                            {item}
                          </li>
                        ))}
                      </ul>
                    )}
                    {Object.keys(metrics).length > 0 && (
                      <div className="evidence-grid">
                        {Object.entries(metrics).map(([k, v]) => (
                          <div key={k} className="evidence-row">
                            <span
                              style={{
                                color: "var(--text-muted)",
                                fontWeight: 500,
                                fontSize: "0.8125rem",
                                textTransform: "capitalize",
                              }}
                            >
                              {k.replace(/_/g, " ")}
                            </span>
                            <span
                              style={{
                                fontFamily: "monospace",
                                fontSize: "0.8125rem",
                                color: "var(--text-primary)",
                              }}
                            >
                              {String(v)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="drawer-section">
                  <div className="drawer-section-title">Recommended Action</div>
                  <p
                    style={{
                      fontSize: "0.875rem",
                      color: "var(--text-secondary)",
                      lineHeight: 1.6,
                    }}
                  >
                    {lo.recommended_action}
                  </p>
                </div>

                <div>
                  <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                    Confidence:{" "}
                    <span
                      style={{ fontWeight: 600, color: "var(--text-primary)" }}
                    >
                      {lo.confidence}
                    </span>
                  </span>
                </div>
              </>
            );
          })()}
        </div>
      </div>
    </>
  );
}
