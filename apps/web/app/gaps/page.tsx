"use client";

import { useEffect, useState } from "react";
import { apiFetch, type ApiResult } from "@/lib/api";
import { ErrorBox, Json, Section } from "@/lib/ui";

type Gap = Record<string, unknown> & {
  id: string;
  gapType: string;
  rankScore: string | null;
  status: string;
  details: Record<string, unknown>;
};

const num = (v: unknown) => (v == null ? null : Number(v));

export default function GapsPage() {
  const [gaps, setGaps] = useState<ApiResult<Gap[]> | null>(null);

  async function load() {
    setGaps(await apiFetch<Gap[]>("/gaps?limit=500"));
  }
  useEffect(() => {
    void load();
  }, []);

  const rows = [...(gaps?.data ?? [])].sort(
    (a, b) => (num(b.rankScore) ?? 0) - (num(a.rankScore) ?? 0),
  );

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold">5. Gaps</h1>
      <Section title="Ranked gaps — GET /gaps">
        <button
          onClick={load}
          className="mb-2 border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
        >
          Refresh
        </button>
        <ErrorBox result={gaps} />
        <table className="mb-2 w-full">
          <thead>
            <tr>
              <th>rankScore</th>
              <th>gapType</th>
              <th>fix_type</th>
              <th>layer</th>
              <th>severity</th>
              <th>status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <tr key={g.id}>
                <td>{num(g.rankScore)?.toFixed(4) ?? "—"}</td>
                <td>{g.gapType}</td>
                <td>{(g.details?.fix_type as string) ?? "—"}</td>
                <td>{(g.details?.layer as string) ?? "—"}</td>
                <td>{(g.details?.severity as string) ?? "—"}</td>
                <td>{g.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && gaps?.ok && (
          <p className="text-sm text-gray-600">
            No gaps. NOTE: gaps come from the Diagnosis stage, which has no API
            trigger and doesn&apos;t run from a scan — see the harness README
            &quot;orchestration&quot; finding.
          </p>
        )}
        <Json data={rows} />
      </Section>
    </div>
  );
}
