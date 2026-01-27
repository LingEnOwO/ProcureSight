"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SessionProvider, signOut, useSession } from "next-auth/react";

const nav = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/uploads", label: "Uploads" },
  { href: "/invoices", label: "Invoices" },
  { href: "/vendors", label: "Vendors" },
  { href: "/alerts", label: "Alerts" },
];

function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: session } = useSession();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="app-name">ProcureSight</div>
          <div className="app-section">Dashboard</div>
        </div>

        <nav className="sidebar-nav">
          {nav.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`sidebar-link ${active ? "active" : ""}`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-meta">Signed in as</div>
          <div className="sidebar-email">{session?.user?.email ?? ""}</div>
        </div>
      </aside>

      <div className="content-shell">
        <header className="topbar">
          <button
            type="button"
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="btn-secondary"
          >
            Sign out
          </button>
        </header>

        <main className="main-content">{children}</main>
      </div>
    </div>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
