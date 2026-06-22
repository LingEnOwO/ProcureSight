import type { ReactNode } from "react";

/**
 * Standard empty-state placeholder shown inside a table wrapper when a list has
 * no rows. The icon varies per page and is passed in; the shell is shared.
 */
export function EmptyState({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="table-wrapper">
      <div className="empty-state">
        <div className="empty-icon">{icon}</div>
        <div className="empty-title">{title}</div>
        <p className="empty-desc">{description}</p>
      </div>
    </div>
  );
}
