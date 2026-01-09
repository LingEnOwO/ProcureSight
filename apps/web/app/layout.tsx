import Link from "next/link";

export const metadata = {
  title: "ProcureSight",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui" }}>
        <div style={{ display: "flex", minHeight: "100vh" }}>
          {/* Sidebar */}
          <aside
            style={{
              width: 220,
              padding: 16,
              borderRight: "1px solid #e5e7eb",
            }}
          >
            <h2>ProcureSight</h2>
            <nav style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <Link href="/dashboard">Dashboard</Link>
              <Link href="/uploads">Uploads</Link>
              <Link href="/invoices">Invoices</Link>
              <Link href="/vendors">Vendors</Link>
              <Link href="/alerts">Alerts</Link>
            </nav>
          </aside>

          {/* Main */}
          <main style={{ flex: 1, padding: 24 }}>{children}</main>
        </div>
      </body>
    </html>
  );
}