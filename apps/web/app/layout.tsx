// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import "./globals.css";
import type { Metadata } from "next";
import { SidebarNav } from "../components/nav";

export const metadata: Metadata = {
  title: "GEO — AI visibility monitoring",
  description:
    "Monitor whether AI engines recommend your brand, and diagnose why not.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      {/* Light mode only — dark mode doubles the surface for no adoption benefit. */}
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        <div className="flex min-h-screen">
          <SidebarNav />
          <main className="min-w-0 flex-1">
            <div className="mx-auto max-w-6xl px-6 py-8">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
