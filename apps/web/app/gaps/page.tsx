// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Gaps, each showing the URL it was found on and the HTTP status of that fetch.
 *
 * Naming the evidence is the whole point. A gap that says "your site is missing
 * X" without saying which URL was checked and what the server answered is an
 * assertion; with them it is a claim the reader can go and verify in one click.
 * That is the difference between this and an SEO tool that just tells you things.
 */
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getJSON } from "../../lib/api";
import {
  Badge,
  Card,
  Empty,
  ErrorBox,
  HttpStatus,
  Loading,
  PageHeader,
  RawJson,
} from "../../components/ui";

type Gap = {
  id: string;
  gapType: string;
  status: string;
  rankScore: string | number | null;
  details: {
    summary?: string;
    severity?: string;
    fix_type?: string;
    page_url?: string;
    detection_confidence?: number;
    evidence?: {
      url?: string;
      status?: number | null;
      truncated?: boolean;
      bytes?: number;
      content_bytes?: number;
      note?: string | null;
      final_url?: string;
    }[];
    reasons?: { summary?: string; finding_code?: string; confidence?: number }[];
  };
};

const SEVERITY_TONE = {
  high: "bad",
  medium: "warn",
  low: "neutral",
  info: "info",
} as const;

export default function GapsPage() {
  const [gaps, setGaps] = useState<Gap[] | null>(null);
  const [err, setErr] = useState<{ status: number; error: string } | null>(null);

  useEffect(() => {
    (async () => {
      const res = await getJSON<Gap[]>("/gaps?limit=100");
      if (!res.ok) setErr({ status: res.status, error: res.error ?? "" });
      else setGaps(res.data ?? []);
    })();
  }, []);

  if (err)
    return (
      <>
        <PageHeader title="Gaps" />
        <ErrorBox status={err.status} error={err.error} context="Could not load gaps" />
      </>
    );
  if (gaps === null) return <Loading what="gaps" />;

  return (
    <>
      <PageHeader
        title="Gaps"
        description="What the site audit found, and the exact evidence behind each finding."
      />

      {gaps.length === 0 ? (
        <Empty title="No gaps found">
          Either the site is clean or no scan has run yet.{" "}
          <Link href="/scans" className="text-blue-700 underline">
            Run a scan
          </Link>
          .
        </Empty>
      ) : (
        <div className="space-y-4">
          {gaps.map((gap) => {
            const d = gap.details ?? {};
            const severity = (d.severity ?? "info") as keyof typeof SEVERITY_TONE;
            const evidence = d.evidence ?? [];
            const confidence = d.detection_confidence;
            return (
              <Card key={gap.id}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-mono text-sm font-semibold text-gray-900">
                        {gap.gapType}
                      </h3>
                      <Badge tone={SEVERITY_TONE[severity] ?? "neutral"}>
                        {severity}
                      </Badge>
                      <Badge tone="neutral">{gap.status}</Badge>
                      {confidence != null && confidence < 1 && (
                        // A low-confidence gap is stored but never ranked. Saying
                        // so stops a weak inference reading like a hard finding.
                        <Badge tone="warn">
                          detection confidence {confidence}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-2 text-sm text-gray-800">
                      {d.summary ?? "(no summary recorded)"}
                    </p>
                  </div>
                  {gap.rankScore != null && (
                    <div className="text-right">
                      <div className="text-xs uppercase text-gray-500">rank</div>
                      <div className="tabular-nums text-sm font-semibold">
                        {Number(gap.rankScore).toFixed(3)}
                      </div>
                    </div>
                  )}
                </div>

                {evidence.length > 0 && (
                  <div className="mt-3 rounded border border-gray-200 bg-gray-50 p-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Evidence
                    </div>
                    <ul className="mt-2 space-y-2">
                      {evidence.map((e, i) => (
                        <li key={i} className="text-sm">
                          <div className="flex flex-wrap items-center gap-2">
                            <HttpStatus status={e.status} />
                            <a
                              href={e.url}
                              target="_blank"
                              rel="noreferrer"
                              className="break-all text-blue-700 underline"
                            >
                              {e.url}
                            </a>
                            {e.truncated && (
                              <Badge tone="warn">
                                truncated — absence not established
                              </Badge>
                            )}
                          </div>
                          {e.final_url && e.final_url !== e.url && (
                            <div className="mt-0.5 text-xs text-gray-500">
                              redirected to {e.final_url}
                            </div>
                          )}
                          {e.bytes != null && (
                            <div className="mt-0.5 text-xs text-gray-500">
                              analysed {e.bytes.toLocaleString()} of{" "}
                              {(e.content_bytes ?? e.bytes).toLocaleString()} bytes
                            </div>
                          )}
                          {e.note && (
                            <div className="mt-0.5 text-xs text-gray-600">{e.note}</div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {(d.reasons?.length ?? 0) > 1 && (
                  <div className="mt-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Merged from {d.reasons!.length} findings
                    </div>
                    <ul className="mt-1 list-inside list-disc text-sm text-gray-700">
                      {d.reasons!.map((r, i) => (
                        <li key={i}>
                          <span className="font-mono text-xs text-gray-500">
                            {r.finding_code}
                          </span>{" "}
                          {r.summary}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <RawJson data={gap} label="raw gap JSON" />
              </Card>
            );
          })}
        </div>
      )}
    </>
  );
}
