// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Sidebar nav, grouped by what the product actually does rather than by the
 * order you happen to click through it.
 *
 * "Fixes" is listed even though this distribution ships no generators: the
 * ranked backlog is real output, and hiding the section would misrepresent what
 * the pipeline produced. The screen says plainly that no generator is
 * registered.
 */
const GROUPS: { label: string; items: [string, string][] }[] = [
  {
    label: "Measure",
    items: [
      ["/leaderboard", "Leaderboard"],
      ["/scans", "Scans"],
    ],
  },
  {
    label: "Diagnose",
    items: [
      ["/gaps", "Gaps"],
      ["/fixes", "Fixes"],
    ],
  },
  {
    label: "Account",
    items: [
      ["/setup", "Setup"],
      ["/costs", "Costs"],
      ["/login", "Sign in"],
    ],
  },
];

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <aside className="w-56 shrink-0 border-r border-gray-200 bg-white">
      <div className="border-b border-gray-200 px-4 py-4">
        <Link href="/" className="block">
          <div className="text-sm font-semibold tracking-tight text-gray-900">
            GEO
          </div>
          <div className="mt-0.5 text-xs text-gray-500">
            AI visibility monitoring
          </div>
        </Link>
      </div>

      <nav className="p-3">
        {GROUPS.map((group) => (
          <div key={group.label} className="mb-4">
            <div className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-gray-400">
              {group.label}
            </div>
            <ul>
              {group.items.map(([href, label]) => {
                const active =
                  pathname === href || pathname.startsWith(`${href}/`);
                return (
                  <li key={href}>
                    <Link
                      href={href}
                      className={`block rounded px-2 py-1.5 text-sm ${
                        active
                          ? "bg-gray-100 font-medium text-gray-900"
                          : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                      }`}
                    >
                      {label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}
