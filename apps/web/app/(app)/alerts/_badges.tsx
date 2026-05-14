export function SeverityBadge({ severity }: { severity: string }) {
  if (!severity || severity === "—")
    return <span style={{ color: "var(--text-muted)" }}>—</span>;
  const s = severity.toLowerCase();
  let cls = "badge badge-gray";
  if (s === "critical" || s === "high") cls = "badge badge-red";
  else if (s === "medium") cls = "badge badge-orange";
  else if (s === "low") cls = "badge badge-yellow";
  return <span className={cls}>{severity}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  if (!status || status === "—")
    return <span style={{ color: "var(--text-muted)" }}>—</span>;
  const s = status.toLowerCase();
  let cls = "badge badge-blue";
  if (s === "open" || s === "active") cls = "badge badge-blue";
  else if (s === "resolved") cls = "badge badge-green";
  else if (s === "dismissed" || s === "acknowledged") cls = "badge badge-gray";
  return <span className={cls}>{status}</span>;
}
