import "./globals.css";
import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "GEO test harness",
  description: "Throwaway click-through harness for the GEO backend",
};

const NAV: [string, string][] = [
  ["/login", "1. Login"],
  ["/setup", "2. Setup"],
  ["/scans", "3. Scans"],
  ["/dashboard", "4. Dashboard"],
  ["/gaps", "5. Gaps"],
  ["/assets", "6. Assets"],
  ["/proof", "7. Proof"],
  ["/costs", "8. Costs"],
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-white text-gray-900">
        <nav className="flex flex-wrap gap-3 border-b border-gray-400 bg-gray-100 p-3 text-sm">
          <span className="font-bold">GEO harness</span>
          {NAV.map(([href, label]) => (
            <Link key={href} href={href} className="text-blue-700 underline">
              {label}
            </Link>
          ))}
        </nav>
        <main className="mx-auto max-w-5xl p-4">{children}</main>
      </body>
    </html>
  );
}
