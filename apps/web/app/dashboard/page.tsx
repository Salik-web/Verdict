"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, type ApiResult } from "@/lib/api";
import { ErrorBox, Json, Section } from "@/lib/ui";

type Sov = Record<string, unknown> & {
  brand: string;
  isSelf: boolean;
  engine: string;
  scanId: string;
  sovPct: string | null;
  mentionCount: number;
  avgPosition: string | null;
};

const num = (v: unknown) => (v == null ? null : Number(v));

export default function DashboardPage() {
  const [sov, setSov] = useState<ApiResult<Sov[]> | null>(null);
  const [engine, setEngine] = useState("all");

  async function load() {
    setSov(await apiFetch<Sov[]>("/share-of-voice?limit=500"));
  }
  useEffect(() => {
    void load();
  }, []);

  const rows = sov?.data ?? [];
  // Rows come newest-first; the leaderboard shows the most recent scan only.
  const latestScanId = rows[0]?.scanId ?? null;
  const engines = useMemo(
    () => Array.from(new Set(rows.filter((r) => r.scanId === latestScanId).map((r) => r.engine))),
    [rows, latestScanId],
  );

  const view = rows
    .filter((r) => r.scanId === latestScanId && r.engine === engine)
    .sort((a, b) => (num(b.sovPct) ?? 0) - (num(a.sovPct) ?? 0));

  const sovSum = view.reduce((acc, r) => acc + (num(r.sovPct) ?? 0), 0);

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold">4. Dashboard (share of voice)</h1>

      <p className="mb-3 text-xs text-gray-600">
        The mock engine answers about a fixed brand set (Acme Analytics, Globex
        Insights, Initech Metrics, Mixpanel, Amplitude). A row is bolded (self)
        only if your account brand name matches one — set brand name to e.g.
        &quot;Acme Analytics&quot; on Setup before scanning to see it.
      </p>

      <Section title="Leaderboard — GET /share-of-voice">
        <div className="mb-2 flex items-center gap-3 text-sm">
          <button
            onClick={load}
            className="border border-gray-500 bg-gray-200 px-2 py-1"
          >
            Refresh
          </button>
          <label>
            engine:{" "}
            <select value={engine} onChange={(e) => setEngine(e.target.value)}>
              {(engines.length ? engines : ["all"]).map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </select>
          </label>
          <span>
            latest scan: <code className="text-xs">{latestScanId ?? "—"}</code>
          </span>
        </div>

        <ErrorBox result={sov} />

        <table className="mb-2 w-full">
          <thead>
            <tr>
              <th>brand</th>
              <th>isSelf</th>
              <th>SoV %</th>
              <th>mentions</th>
              <th>avg position</th>
            </tr>
          </thead>
          <tbody>
            {view.map((r, i) => (
              <tr key={`${r.brand}-${i}`} className={r.isSelf ? "font-bold" : ""}>
                <td>{r.brand}</td>
                <td>{String(r.isSelf)}</td>
                <td>{num(r.sovPct)?.toFixed(2)}</td>
                <td>{r.mentionCount}</td>
                <td>{num(r.avgPosition)?.toFixed(2) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-gray-100">
              <td colSpan={2}>
                SoV sum (should be ~100 for engine group)
              </td>
              <td className={Math.abs(sovSum - 100) < 0.5 ? "" : "bg-red-100"}>
                {sovSum.toFixed(2)}
              </td>
              <td colSpan={2}></td>
            </tr>
          </tfoot>
        </table>

        {rows.length === 0 && sov?.ok && (
          <p className="text-sm text-gray-600">
            No share-of-voice rows — run a scan and wait for it to complete.
          </p>
        )}
        <Json data={rows} />
      </Section>
    </div>
  );
}
