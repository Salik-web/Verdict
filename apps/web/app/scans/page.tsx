// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Scans: trigger one, and watch it progress stage by stage.
 *
 * A scan takes minutes (deliberate spacing between rate-limited calls), so the
 * running state has to look intentional rather than hung. Per-stage progress is
 * read straight from `scans.stats.stages`, which is exactly what the pipeline
 * records — no separate progress channel to drift out of sync.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../../lib/api";
import {
  Badge,
  Button,
  Card,
  Cell,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  RawJson,
  Row,
  Table,
  when,
} from "../../components/ui";
import { EngineBanner } from "../../components/engines";

type Scan = {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  createdAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  error?: string | null;
  engineSet?: unknown;
  stats?: { stages?: Record<string, any> };
};

const STATUS_TONE = {
  completed: "good",
  running: "info",
  pending: "neutral",
  failed: "bad",
} as const;

const STAGES = ["monitor", "diagnosis", "execution"];

export default function ScansPage() {
  const [scans, setScans] = useState<Scan[] | null>(null);
  const [err, setErr] = useState<{ status: number; error: string } | null>(null);
  const [triggering, setTriggering] = useState(false);

  const load = useCallback(async () => {
    const res = await getJSON<Scan[]>("/scans");
    if (!res.ok) setErr({ status: res.status, error: res.error ?? "" });
    else {
      setScans(res.data ?? []);
      setErr(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll only while something is actually in flight, so an idle page is quiet.
  const active = (scans ?? []).some(
    (s) => s.status === "running" || s.status === "pending",
  );
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [active, load]);

  async function trigger() {
    setTriggering(true);
    const res = await postJSON("/scans", { engines: ["all"] });
    setTriggering(false);
    if (!res.ok) setErr({ status: res.status, error: res.error ?? "" });
    else load();
  }

  return (
    <>
      <PageHeader
        title="Scans"
        description="Monitor → Diagnose → Plan. One trigger runs the whole loop."
        actions={
          <Button onClick={trigger} disabled={triggering}>
            {triggering ? "Starting…" : "Run a scan"}
          </Button>
        }
      />

      {/* What this scan will actually be able to measure, before it is run. */}
      <EngineBanner />

      {err && (
        <div className="mb-4">
          <ErrorBox status={err.status} error={err.error} context="Scan request failed" />
        </div>
      )}

      {scans === null ? (
        <Loading what="scans" />
      ) : scans.length === 0 ? (
        <Empty title="No scans yet">
          Run one above. In <code>GATEWAY_MODE=mock</code> it costs nothing and
          finishes in seconds; against real engines it takes a few minutes,
          because calls are deliberately spaced to respect rate limits.
        </Empty>
      ) : (
        <div className="space-y-4">
          {active && (
            <div className="rounded-md border border-blue-300 bg-blue-50 p-3 text-sm text-blue-900">
              A scan is running. Refreshing every 5s. Real scans take minutes —
              the pipeline spaces its calls on purpose.
            </div>
          )}
          {scans.map((scan) => {
            const stages = scan.stats?.stages ?? {};
            return (
              <Card key={scan.id}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <Badge tone={STATUS_TONE[scan.status] ?? "neutral"}>
                        {scan.status}
                      </Badge>
                      <span className="font-mono text-xs text-gray-500">
                        {scan.id}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-gray-500">
                      started {when(scan.startedAt ?? scan.createdAt)}
                      {scan.finishedAt && ` · finished ${when(scan.finishedAt)}`}
                    </div>
                  </div>
                  <div className="flex gap-1">
                    {STAGES.map((s) => (
                      <Badge
                        key={s}
                        tone={
                          stages[s]
                            ? "good"
                            : scan.status === "failed"
                              ? "bad"
                              : "neutral"
                        }
                      >
                        {s}
                      </Badge>
                    ))}
                  </div>
                </div>

                {scan.error && (
                  <div className="mt-3">
                    <ErrorBox error={scan.error} context="Scan failed" />
                  </div>
                )}

                {stages.monitor && (
                  <div className="mt-3">
                    <Table head={["Stage", "Result"]}>
                      <Row>
                        <Cell className="font-medium">monitor</Cell>
                        <Cell>
                          {stages.monitor.mentions} mentions ·{" "}
                          {stages.monitor.observations_used}/
                          {stages.monitor.observations_requested} observations
                          used
                          {stages.monitor.failed_observations?.length > 0 && (
                            <span className="ml-2">
                              <Badge tone="warn">
                                {stages.monitor.failed_observations.length}{" "}
                                dropped
                              </Badge>
                            </span>
                          )}
                        </Cell>
                      </Row>
                      {stages.diagnosis && (
                        <Row>
                          <Cell className="font-medium">diagnosis</Cell>
                          <Cell>
                            {stages.diagnosis.findings} findings ·{" "}
                            {stages.diagnosis.gaps} gaps
                            {stages.diagnosis.skipped && (
                              <Badge tone="neutral">
                                skipped: {stages.diagnosis.reason}
                              </Badge>
                            )}
                          </Cell>
                        </Row>
                      )}
                      {stages.execution && (
                        <Row>
                          <Cell className="font-medium">execution</Cell>
                          <Cell>
                            {stages.execution.skipped_generation ? (
                              <Badge tone="neutral">
                                planned only — no generator registered
                              </Badge>
                            ) : stages.execution.asset_id ? (
                              <>asset {stages.execution.type}</>
                            ) : (
                              <>{stages.execution.reason ?? "—"}</>
                            )}
                          </Cell>
                        </Row>
                      )}
                    </Table>
                  </div>
                )}

                <RawJson data={scan} label="raw scan JSON" />
              </Card>
            );
          })}
        </div>
      )}
    </>
  );
}
