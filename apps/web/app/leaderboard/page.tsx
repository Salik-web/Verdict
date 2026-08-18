// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * The leaderboard: who the AI engines actually name, and where you sit.
 *
 * This is the single most useful thing the project produces, so it earns the
 * most care. Three things it must get right:
 *
 *  1. YOUR BRAND IS ALWAYS SHOWN, even at 0% — especially at 0%. Being absent
 *     is the finding. A table that silently omits you because you scored zero
 *     would hide the entire point.
 *  2. DISCOVERED competitors are flagged distinctly from tracked ones. A brand
 *     the engines named that you never configured is a genuine discovery, and
 *     conflating the two hides it.
 *  3. The denominator is stated. Share of voice over 8 observations is not the
 *     same claim as over 800, and the header says which it is.
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
  Stat,
  Table,
  pct,
} from "../../components/ui";

type SovRow = {
  id: string;
  scanId: string;
  brand: string;
  isSelf: boolean;
  competitorId: string | null;
  engine: string;
  mentionCount: number;
  mentionRate: string | number | null;
  avgPosition: string | number | null;
  sovPct: string | number | null;
  details?: Record<string, unknown>;
};

type Scan = { id: string; status: string; createdAt: string; stats?: any };

export default function LeaderboardPage() {
  const [rows, setRows] = useState<SovRow[] | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [err, setErr] = useState<{ status: number; error: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      const scans = await getJSON<Scan[]>("/scans");
      if (!scans.ok) {
        setErr({ status: scans.status, error: scans.error ?? "" });
        setLoading(false);
        return;
      }
      // Newest COMPLETED scan — a running scan has partial rows, and showing a
      // half-finished leaderboard as if it were final would misreport.
      const completed = (scans.data ?? []).find((s) => s.status === "completed");
      setScan(completed ?? null);

      const q = completed ? `?scan_id=${completed.id}&limit=200` : "?limit=200";
      const sov = await getJSON<SovRow[]>(`/share-of-voice${q}`);
      if (!sov.ok) setErr({ status: sov.status, error: sov.error ?? "" });
      else setRows(sov.data ?? []);
      setLoading(false);
    })();
  }, []);

  if (loading) return <Loading what="the leaderboard" />;
  if (err)
    return (
      <>
        <PageHeader title="Leaderboard" />
        <ErrorBox
          status={err.status}
          error={err.error}
          context="Could not load share of voice"
        />
      </>
    );

  // One row per brand: the API returns a per-engine row AND an `all` aggregate.
  // The aggregate is the honest cross-engine number.
  const all = (rows ?? []).filter((r) => r.engine === "all");
  const perEngine = (rows ?? []).filter((r) => r.engine !== "all");
  const engines = [...new Set(perEngine.map((r) => r.engine))];

  const ranked = [...all].sort(
    (a, b) => Number(b.sovPct ?? 0) - Number(a.sovPct ?? 0),
  );
  const self = ranked.find((r) => r.isSelf);
  const selfRank = self ? ranked.indexOf(self) + 1 : null;
  const observations = scan?.stats?.stages?.monitor?.observations_used ?? null;
  const requested = scan?.stats?.stages?.monitor?.observations_requested ?? null;

  return (
    <>
      <PageHeader
        title="Leaderboard"
        description={
          scan
            ? `Brands the AI engines named, from the latest completed scan.`
            : "Brands the AI engines named."
        }
      />

      {ranked.length === 0 ? (
        <Empty title="No measurements yet">
          Run a scan to see which brands the engines recommend.{" "}
          <Link href="/scans" className="text-blue-700 underline">
            Go to scans
          </Link>
          .
        </Empty>
      ) : (
        <>
          <div className="mb-6 grid gap-3 sm:grid-cols-4">
            <Stat
              label="Your share of voice"
              value={self ? pct(Number(self.sovPct) / 100) : "0.0%"}
              hint={self?.brand ?? "your brand"}
            />
            <Stat
              label="Your rank"
              value={selfRank ? `#${selfRank}` : "unranked"}
              hint={`of ${ranked.length} brands named`}
            />
            <Stat
              label="Observations"
              value={observations ?? "—"}
              hint={
                requested != null && observations != null && requested !== observations
                  ? `${requested} requested, ${requested - observations} dropped`
                  : "answers the engines returned"
              }
            />
            <Stat
              label="Engines"
              value={engines.length || "—"}
              hint={engines.join(", ") || "none"}
            />
          </div>

          {self && Number(self.mentionCount) === 0 && (
            <div className="mb-6 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              <strong>{self.brand} was not named in any answer.</strong> That is
              the measurement, not an error — the engines recommended{" "}
              {ranked.length - 1} other brands instead. The gaps below are the
              diagnosis.{" "}
              <Link href="/gaps" className="underline">
                See gaps
              </Link>
              .
            </div>
          )}

          <Card
            title={`${ranked.length} brands named`}
            description={
              observations
                ? `Share of voice across ${observations} answer(s). Small samples move a lot between scans.`
                : undefined
            }
          >
            <Table
              head={["#", "Brand", "", "Mentions", "Mention rate", "Share of voice"]}
            >
              {ranked.map((r, i) => (
                <Row key={r.id} highlight={r.isSelf}>
                  <Cell className="tabular-nums text-gray-500">{i + 1}</Cell>
                  <Cell
                    className={r.isSelf ? "font-semibold text-gray-900" : ""}
                  >
                    {r.brand}
                  </Cell>
                  <Cell>
                    {r.isSelf ? (
                      <Badge tone="info">you</Badge>
                    ) : r.competitorId ? (
                      <Badge tone="neutral">tracked</Badge>
                    ) : (
                      // Named by an engine but never configured — a real find.
                      <Badge tone="warn">discovered</Badge>
                    )}
                  </Cell>
                  <Cell className="tabular-nums">{r.mentionCount}</Cell>
                  <Cell className="tabular-nums">{pct(r.mentionRate)}</Cell>
                  <Cell className="tabular-nums">
                    <div className="flex items-center gap-2">
                      <span className="w-14">
                        {Number(r.sovPct ?? 0).toFixed(2)}%
                      </span>
                      <span
                        className="inline-block h-2 rounded-sm bg-gray-400"
                        style={{
                          width: `${Math.max(2, Math.min(100, Number(r.sovPct ?? 0) * 3))}px`,
                        }}
                        aria-hidden
                      />
                    </div>
                  </Cell>
                </Row>
              ))}
            </Table>
            <p className="mt-3 text-xs text-gray-500">
              <strong>tracked</strong> = a competitor you configured.{" "}
              <strong>discovered</strong> = a brand the engines named that you
              have not configured. Entity resolution merges surface forms (e.g.
              &ldquo;DALL-E&rdquo; into &ldquo;DALL-E 3&rdquo;); merged rows list
              their source forms in the raw JSON.
            </p>
            <RawJson data={rows} />
          </Card>
        </>
      )}
    </>
  );
}
