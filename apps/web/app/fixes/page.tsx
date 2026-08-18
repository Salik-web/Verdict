// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * The ranked backlog — shown even though this distribution generates nothing.
 *
 * Hiding this section would be the dishonest choice. Planning genuinely ran: it
 * scored every gap on impact x control x confidence and ordered them. That
 * ranking is real, useful output on its own — it tells you what to fix first,
 * whether or not software writes the fix for you.
 *
 * So the page shows the backlog and states plainly that no generator is
 * registered, rather than rendering a button that does nothing.
 */
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getJSON } from "../../lib/api";
import {
  Badge,
  Card,
  Cell,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  RawJson,
  Row,
  Table,
} from "../../components/ui";

type Scan = {
  id: string;
  status: string;
  createdAt: string;
  stats?: {
    stages?: {
      execution?: {
        skipped_generation?: boolean;
        reason?: string;
        unsupported_fix_types?: string[];
        backlog?: [string, number][];
        asset_id?: string;
        type?: string;
        status?: string;
        blocked?: boolean;
      };
    };
  };
};

export default function FixesPage() {
  const [scan, setScan] = useState<Scan | null>(null);
  const [err, setErr] = useState<{ status: number; error: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const res = await getJSON<Scan[]>("/scans");
      if (!res.ok) setErr({ status: res.status, error: res.error ?? "" });
      else
        setScan(
          (res.data ?? []).find(
            (s) => s.status === "completed" && s.stats?.stages?.execution,
          ) ?? null,
        );
      setLoading(false);
    })();
  }, []);

  if (loading) return <Loading what="the backlog" />;
  if (err)
    return (
      <>
        <PageHeader title="Fixes" />
        <ErrorBox status={err.status} error={err.error} context="Could not load scans" />
      </>
    );

  const exec = scan?.stats?.stages?.execution;
  const backlog = exec?.backlog ?? [];

  return (
    <>
      <PageHeader
        title="Fixes"
        description="Gaps ranked by impact × control × confidence. The order is the recommendation."
      />

      {!exec ? (
        <Empty title="No plan yet">
          Run a scan to rank your gaps.{" "}
          <Link href="/scans" className="text-blue-700 underline">
            Go to scans
          </Link>
          .
        </Empty>
      ) : (
        <>
          {exec.skipped_generation && (
            <div className="mb-6 rounded-md border border-gray-300 bg-gray-100 p-4">
              <div className="flex items-center gap-2">
                <Badge tone="neutral">no generator registered</Badge>
              </div>
              <p className="mt-2 text-sm text-gray-800">
                This build ships no content generators, so nothing was written
                for you. The ranking below still ran and is the useful part.
              </p>
              <p className="mt-2 text-xs text-gray-600">
                {exec.reason}
              </p>
              <p className="mt-2 text-xs text-gray-600">
                Generators are an extension point: implement{" "}
                <code className="rounded bg-white px-1">Generator</code> and
                register it on the{" "}
                <code className="rounded bg-white px-1">geo.generators</code>{" "}
                entry point. See{" "}
                <span className="font-mono">docs/WRITING-A-GENERATOR.md</span>.
              </p>
            </div>
          )}

          {exec.blocked && (
            <div className="mb-6 rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
              <strong>Generation was refused.</strong> {exec.reason}
            </div>
          )}

          {backlog.length === 0 ? (
            <Empty title="Nothing rankable">
              Gaps below the planner&rsquo;s detection-confidence floor are
              recorded for the report but never ranked, so a weak single-page
              inference can never become the top recommendation.
            </Empty>
          ) : (
            <Card title={`${backlog.length} ranked fix types`}>
              <Table head={["#", "Fix type", "Score", "Status"]}>
                {backlog.map(([fixType, score], i) => {
                  const unsupported = (
                    exec.unsupported_fix_types ?? []
                  ).includes(fixType);
                  return (
                    <Row key={fixType}>
                      <Cell className="tabular-nums text-gray-500">{i + 1}</Cell>
                      <Cell className="font-mono text-sm">{fixType}</Cell>
                      <Cell className="tabular-nums">{score.toFixed(4)}</Cell>
                      <Cell>
                        {unsupported ? (
                          <Badge tone="neutral">
                            no generator available for this fix type
                          </Badge>
                        ) : (
                          <Badge tone="good">generated</Badge>
                        )}
                      </Cell>
                    </Row>
                  );
                })}
              </Table>
              <RawJson data={exec} label="raw execution stage JSON" />
            </Card>
          )}
        </>
      )}
    </>
  );
}
