import React from "react";

export const metadata = {
  title: "ProcureSight",
  description: "Invoice & contract intelligence",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui", margin: 0 }}>
        {children}
      </body>
    </html>
  );
}
