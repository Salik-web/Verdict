// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import Link from "next/link";
import { Card, PageHeader } from "../components/ui";

const STEPS: [string, string, string][] = [
  ["/login", "Sign in", "Use the demo account, or create your own."],
  [
    "/setup",
    "Set up",
    "Generate buyer-intent prompts and confirm your brand and competitors.",
  ],
  [
    "/scans",
    "Run a scan",
    "Monitor → Diagnose → Plan. Free in mock mode; a few minutes against real engines.",
  ],
  [
    "/leaderboard",
    "Read the leaderboard",
    "Which brands the engines actually name, and where you sit.",
  ],
  [
    "/gaps",
    "Review gaps",
    "Each finding names the URL it checked and what the server answered.",
  ],
];

export default function Home() {
  return (
    <>
      <PageHeader
        title="GEO"
        description="Monitor whether AI engines recommend your brand, and diagnose why not."
      />

      <Card title="Getting started" className="mb-6">
        <ol className="space-y-3">
          {STEPS.map(([href, title, blurb], i) => (
            <li key={href} className="flex gap-3">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-200 text-xs font-semibold text-gray-700">
                {i + 1}
              </span>
              <div>
                <Link
                  href={href}
                  className="text-sm font-medium text-blue-700 underline"
                >
                  {title}
                </Link>
                <p className="text-sm text-gray-600">{blurb}</p>
              </div>
            </li>
          ))}
        </ol>
      </Card>

      <Card title="What this build does and doesn't do">
        <ul className="list-inside list-disc space-y-1 text-sm text-gray-700">
          <li>
            <strong>Monitoring and diagnosis are the product here.</strong> Both
            run end to end.
          </li>
          <li>
            <strong>Content generation is not included.</strong> Planning ranks
            your gaps and stops; generators are an extension point you can
            implement. See <span className="font-mono">/fixes</span>.
          </li>
          <li>
            <strong>Defaults cost nothing.</strong>{" "}
            <span className="font-mono">GATEWAY_MODE=mock</span> runs the whole
            pipeline against fixtures with no API keys.
          </li>
          <li>
            <strong>Bring your own keys.</strong> Supply only the engines you
            want — one key gives you a working one-engine scan.
          </li>
        </ul>
      </Card>
    </>
  );
}
