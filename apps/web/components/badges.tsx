/**
 * Shared status/severity badges.
 *
 * Alerts and invoices use DIFFERENT status vocabularies, so their status badges
 * are deliberately kept as separate components (AlertStatusBadge vs
 * InvoiceStatusBadge) rather than merged — only the rendering shell is shared.
 */

function MutedDash() {
  return <span style={{ color: "var(--text-muted)" }}>—</span>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  if (!severity || severity === "—") return <MutedDash />;
  const s = severity.toLowerCase();
  let cls = "badge badge-gray";
  if (s === "critical" || s === "high") cls = "badge badge-red";
  else if (s === "medium") cls = "badge badge-orange";
  else if (s === "low") cls = "badge badge-yellow";
  return <span className={cls}>{severity}</span>;
}

/** Alert lifecycle: open / active / resolved / dismissed / acknowledged. */
export function AlertStatusBadge({ status }: { status: string }) {
  if (!status || status === "—") return <MutedDash />;
  const s = status.toLowerCase();
  let cls = "badge badge-blue";
  if (s === "open" || s === "active") cls = "badge badge-blue";
  else if (s === "resolved") cls = "badge badge-green";
  else if (s === "dismissed" || s === "acknowledged") cls = "badge badge-gray";
  return <span className={cls}>{status}</span>;
}

/** Invoice lifecycle: paid / pending / overdue / processing / cancelled. */
export function InvoiceStatusBadge({ status }: { status: string }) {
  if (!status || status === "—") return <MutedDash />;
  const s = status.toLowerCase();
  let cls = "badge badge-gray";
  if (s === "paid") cls = "badge badge-green";
  else if (s === "pending") cls = "badge badge-yellow";
  else if (s === "overdue") cls = "badge badge-red";
  else if (s === "processing") cls = "badge badge-blue";
  else if (s === "cancelled" || s === "canceled") cls = "badge badge-gray";
  return <span className={cls}>{status}</span>;
}
