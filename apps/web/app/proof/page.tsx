// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Verification: did a shipped fix actually move anything?
 *
 * `no_change` and `inconclusive` are rendered exactly as plainly as `improved`.
 * They are first-class results — a verification that refuses to call a 5-sample
 * comparison is doing its job, not failing — and a UI that shouts about wins
 * while whispering about nulls is lying by typography.
 *
 * Confidence is shown next to the sample size that produced it, because a
 * confidence figure without its denominator is decoration.
 */
"use client";

import { useEffect, useState } from "react";
import { getJSON } from "../../lib/api";
import {
  Card,
  Cell,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  RawJson,
  Row,
  Table,
  Verdict,
  pct,
  when,
} from "../../components/ui";

type Metrics = {
  observations: number;
  mentioned_count: number;
  mention_rate: number;
  avg_position: number | null;
};
type Verification = {
  id: string;
  assetId: string;
  verdict: string;
  confidence: string | number;
  beforeMetrics: Metrics;
  afterMetrics: Metrics;
  createdAt: string;
};

export default function ProofPage() {
  const [rows, setRows] = useState<Verification[] | null>(null);
  const [err, setErr] = useState<{ status: number; error: string } | null>(null);

  useEffect(() => {
    (async () => {
      const res = await getJSON<Verification[]>("/verifications?limit=50");
      if (!res.ok) setErr({ status: res.status, error: res.error ?? "" });
      else setRows(res.data ?? []);
    })();
  }, []);

  if (err)
    return (
      <>
        <PageHeader title="Proof" />
        <ErrorBox
          status={err.status}
          error={err.error}
          context="Could not load verifications"
        />
      </>
    );
  if (rows === null) return <Loading what="verifications" />;

  return (
    <>
      <PageHeader
        title="Proof"
        description="Before/after visibility for shipped fixes. Honest verdicts — 'no change' and 'inconclusive' are results, not failures."
      />

      {rows.length === 0 ? (
        <Empty title="Nothing verified yet">
          Verification re-runs a shipped asset&rsquo;s exact prompts after it has
          had time to be crawled. This build ships no generators, so nothing is
          produced to verify unless you register one.
        </Empty>
      ) : (
        <div className="space-y-4">
          {rows.map((v) => {
            const delta =
              Number(v.afterMetrics?.mention_rate ?? 0) -
              Number(v.beforeMetrics?.mention_rate ?? 0);
            const sample = Math.min(
              v.beforeMetrics?.observations ?? 0,
              v.afterMetrics?.observations ?? 0,
            );
            return (
              <Card key={v.id}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Verdict verdict={v.verdict} />
                    <span className="text-sm text-gray-600">
                      confidence {Number(v.confidence).toFixed(4)}
                    </span>
                    <span className="text-xs text-gray-500">
                      on {sample} observation(s) per side
                    </span>
                  </div>
                  <span className="text-xs text-gray-500">
                    {when(v.createdAt)}
                  </span>
                </div>

                <div className="mt-3">
                  <Table
                    head={["", "Observations", "Mentions", "Mention rate"]}
                  >
                    <Row>
                      <Cell className="font-medium">before</Cell>
                      <Cell className="tabular-nums">
                        {v.beforeMetrics?.observations ?? "—"}
                      </Cell>
                      <Cell className="tabular-nums">
                        {v.beforeMetrics?.mentioned_count ?? "—"}
                      </Cell>
                      <Cell className="tabular-nums">
                        {pct(v.beforeMetrics?.mention_rate)}
                      </Cell>
                    </Row>
                    <Row>
                      <Cell className="font-medium">after</Cell>
                      <Cell className="tabular-nums">
                        {v.afterMetrics?.observations ?? "—"}
                      </Cell>
                      <Cell className="tabular-nums">
                        {v.afterMetrics?.mentioned_count ?? "—"}
                      </Cell>
                      <Cell className="tabular-nums">
                        {pct(v.afterMetrics?.mention_rate)}
                      </Cell>
                    </Row>
                  </Table>
                </div>

                <p className="mt-3 text-sm text-gray-700">
                  Change in self mention-rate:{" "}
                  <span className="tabular-nums font-medium">
                    {delta >= 0 ? "+" : ""}
                    {(delta * 100).toFixed(1)}pp
                  </span>
                  {v.verdict === "inconclusive" && (
                    <> — below the minimum sample to call either way.</>
                  )}
                </p>

                <RawJson data={v} label="raw verification JSON" />
              </Card>
            );
          })}
        </div>
      )}
    </>
  );
}
