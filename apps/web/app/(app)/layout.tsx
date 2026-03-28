"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SessionProvider, signOut, useSession } from "next-auth/react";

const nav = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <rect x="1" y="1" width="5.5" height="5.5" rx="1.25" fill="currentColor" />
        <rect x="8.5" y="1" width="5.5" height="5.5" rx="1.25" fill="currentColor" opacity="0.4" />
        <rect x="1" y="8.5" width="5.5" height="5.5" rx="1.25" fill="currentColor" opacity="0.4" />
        <rect x="8.5" y="8.5" width="5.5" height="5.5" rx="1.25" fill="currentColor" />
      </svg>
    ),
  },
  {
    href: "/uploads",
    label: "Uploads",
    icon: (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <path
          d="M7.5 10V2.5M7.5 2.5L4.5 5.5M7.5 2.5L10.5 5.5"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M1.5 10.5V11.5C1.5 12.052 1.948 12.5 2.5 12.5H12.5C13.052 12.5 13.5 12.052 13.5 11.5V10.5"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    href: "/invoices",
    label: "Invoices",
    icon: (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <rect
          x="2"
          y="1"
          width="11"
          height="13"
          rx="1.5"
          stroke="currentColor"
          strokeWidth="1.4"
        />
        <path
          d="M5 5h5M5 7.5h5M5 10h3"
          stroke="currentColor"
          strokeWidth="1.25"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
  {
    href: "/vendors",
    label: "Vendors",
    icon: (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <circle cx="5.5" cy="4.5" r="2.25" stroke="currentColor" strokeWidth="1.4" />
        <path
          d="M1 13c0-2.485 2.015-4 4.5-4s4.5 1.515 4.5 4"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
        <circle cx="11.5" cy="4.5" r="1.75" stroke="currentColor" strokeWidth="1.25" opacity="0.5" />
        <path
          d="M13.5 13c0-1.5-.9-2.6-2-3.1"
          stroke="currentColor"
          strokeWidth="1.25"
          strokeLinecap="round"
          opacity="0.5"
        />
      </svg>
    ),
  },
  {
    href: "/alerts",
    label: "Alerts",
    icon: (
      <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
        <path
          d="M7.5 1.5C5.015 1.5 3 3.515 3 6v3L1.5 10.5h12L12 9V6c0-2.485-2.015-4.5-4.5-4.5z"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
        <path
          d="M6 12a1.5 1.5 0 003 0"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </svg>
    ),
  },
];

function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: session } = useSession();
  const email = session?.user?.email ?? "";
  const initial = email[0]?.toUpperCase() ?? "U";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <div className="sidebar-brand-icon">PS</div>
            <span className="sidebar-brand-name">ProcureSight</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          {nav.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`sidebar-link${active ? " active" : ""}`}
              >
                {item.icon}
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-user">
            <div className="sidebar-avatar">{initial}</div>
            <span className="sidebar-email">{email}</span>
          </div>
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
