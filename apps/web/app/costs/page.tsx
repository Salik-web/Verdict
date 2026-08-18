// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Cost ledger.
 *
 * The number shown is MODELLED, not billed: pricing comes from
 * config/models.yaml, so a call served by a free tier still shows its list
 * price. That makes unit economics meaningful ("what would this cost at scale?")
 * but it is not your invoice, and the page says so rather than letting someone
 * quote it as spend.
 */
"use client";

import { useEffect, useState } from "react";
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
  Stat,
  Table,
  money,
} from "../../components/ui";

type Summary = {
  calls: number;
  real_calls: number;
  mock_calls: number;
  cost_usd?: number | string;
  by_model?: Record<string, { calls: number; cost_usd: number | string }>;
  by_operation?: Record<string, { calls: number; cost_usd: number | string }>;
  [k: string]: unknown;
};

export default function CostsPage() {
  const [data, setData] = useState<Summary | null>(null);
  const [err, setErr] = useState<{ status: number; error: string } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        // Proxied server-side: the pipeline's cost endpoint needs the internal
        // shared secret, which must never reach the browser.
        const res = await fetch("/api/costs?days=30");
        const text = await res.text();
        let parsed: unknown = null;
        try {
          parsed = text ? JSON.parse(text) : null;
        } catch {
          parsed = text;
        }
        if (!res.ok) {
          setErr({
            status: res.status,
            error:
              typeof parsed === "string"
                ? parsed
                : JSON.stringify(parsed, null, 2),
          });
        } else setData(parsed as Summary);
      } catch (e) {
        setErr({ status: 0, error: String(e) });
      }
    })();
  }, []);

  if (err)
    return (
      <>
        <PageHeader title="Costs" />
        <ErrorBox
          status={err.status}
          error={err.error}
          context="Could not load the cost ledger"
        />
      </>
    );
  if (!data) return <Loading what="costs" />;

  const byOp = data.by_operation ?? {};
  const byModel = data.by_model ?? {};

  return (
    <>
      <PageHeader
        title="Costs"
        description="Every model call this account issued in the last 30 days."
      />

      <div className="mb-4 rounded-md border border-gray-300 bg-gray-100 p-3 text-xs text-gray-700">
        <strong>Modelled, not billed.</strong> Prices come from
        <code className="mx-1 rounded bg-white px-1">config/models.yaml</code>,
        so a call served by a free tier still shows its list price. Useful for
        unit economics; not your invoice.
      </div>

      {data.calls === 0 ? (
        <Empty title="No calls logged yet">
          Run a scan and every model call will appear here — including cache
          hits (flagged, zero cost) and failures.
        </Empty>
      ) : (
        <>
          <div className="mb-6 grid gap-3 sm:grid-cols-4">
            <Stat label="Calls" value={data.calls} />
            <Stat
              label="Real calls"
              value={data.real_calls}
              hint={`${data.mock_calls} mock`}
            />
            <Stat label="Modelled cost" value={money(data.cost_usd as number, 4)} />
            <Stat
              label="Per scan"
              value={
                data.calls > 0
                  ? money(Number(data.cost_usd ?? 0) / Math.max(1, data.calls), 5)
                  : "—"
              }
              hint="per call average"
            />
          </div>

          {Object.keys(byOp).length > 0 && (
            <Card title="By operation" className="mb-4">
              <Table head={["Operation", "Calls", "Modelled cost"]}>
                {Object.entries(byOp).map(([op, v]) => (
                  <Row key={op}>
                    <Cell className="font-mono text-sm">{op}</Cell>
                    <Cell className="tabular-nums">{v.calls}</Cell>
                    <Cell className="tabular-nums">{money(v.cost_usd)}</Cell>
                  </Row>
                ))}
              </Table>
            </Card>
          )}

          {Object.keys(byModel).length > 0 && (
            <Card title="By model">
              <Table head={["Model", "Calls", "Modelled cost"]}>
                {Object.entries(byModel).map(([model, v]) => (
                  <Row key={model}>
                    <Cell className="font-mono text-sm">
                      {model}
                      {model.startsWith("mock/") && (
                        <span className="ml-2">
                          <Badge tone="neutral">simulated</Badge>
                        </span>
                      )}
                    </Cell>
                    <Cell className="tabular-nums">{v.calls}</Cell>
                    <Cell className="tabular-nums">{money(v.cost_usd)}</Cell>
                  </Row>
                ))}
              </Table>
            </Card>
          )}

          <RawJson data={data} label="raw cost JSON" />
        </>
      )}
    </>
  );
}
