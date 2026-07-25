"use client";

import { useEffect, useState } from "react";
import { apiFetch, type ApiResult } from "@/lib/api";
import { ErrorBox, Json, Section } from "@/lib/ui";

type Metrics = { mention_rate?: number; observations?: number };
type Verification = Record<string, unknown> & {
  id: string;
  assetId: string;
  verdict: string;
  confidence: string | null;
  beforeMetrics: Metrics;
  afterMetrics: Metrics;
  scanBeforeId: string | null;
  scanAfterId: string | null;
};

const rate = (m: Metrics | undefined) =>
  m?.mention_rate == null ? "—" : m.mention_rate.toFixed(3);

export default function ProofPage() {
  const [list, setList] = useState<ApiResult<Verification[]> | null>(null);

  async function load() {
    setList(await apiFetch<Verification[]>("/verifications?limit=500"));
  }
  useEffect(() => {
    void load();
  }, []);

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold">7. Proof (verifications)</h1>
      <Section title="Before / after per shipped asset — GET /verifications">
        <p className="mb-2 text-xs text-gray-600">
          Every verdict rendered the same — this is a correctness check, not a
          sales screen. &quot;no_change&quot; and &quot;inconclusive&quot; are
          valid, honest outcomes.
        </p>
        <button
          onClick={load}
          className="mb-2 border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
        >
          Refresh
        </button>
        <ErrorBox result={list} />
        <table className="mb-2 w-full">
          <thead>
            <tr>
              <th>assetId</th>
              <th>verdict</th>
              <th>confidence</th>
              <th>before rate</th>
              <th>after rate</th>
              <th>scanBefore → scanAfter</th>
            </tr>
          </thead>
          <tbody>
            {(list?.data ?? []).map((v) => (
              <tr key={v.id}>
                <td className="font-mono text-xs">{v.assetId}</td>
                <td>{v.verdict}</td>
                <td>{v.confidence == null ? "—" : Number(v.confidence).toFixed(3)}</td>
                <td>{rate(v.beforeMetrics)}</td>
                <td>{rate(v.afterMetrics)}</td>
                <td className="font-mono text-xs">
                  {(v.scanBeforeId ?? "—").slice(0, 8)} →{" "}
                  {(v.scanAfterId ?? "—").slice(0, 8)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(list?.data?.length ?? 0) === 0 && list?.ok && (
          <p className="text-sm text-gray-600">
            No verifications. NOTE: these come from the Verification stage, which
            the product can&apos;t trigger through the API — see the harness
            README &quot;orchestration&quot; finding.
          </p>
        )}
        <Json data={list?.data} />
      </Section>
    </div>
  );
}
