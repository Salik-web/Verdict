"use client";

import { useEffect, useState } from "react";
import { type ApiResult } from "@/lib/api";
import { ErrorBox, Json, Section } from "@/lib/ui";

type ModelRow = {
  provider: string;
  model: string;
  calls: number;
  cost_usd: number;
  total_tokens: number;
};
type Costs = {
  account_id: string;
  calls: number;
  cost_usd: number;
  total_tokens: number;
  mock_calls: number;
  real_calls: number;
  by_model: ModelRow[];
};

// This screen hits the SAME-ORIGIN Next proxy (/api/costs), not the API directly.
async function fetchCosts(): Promise<ApiResult<Costs>> {
  let res: Response;
  try {
    res = await fetch("/api/costs?days=30");
  } catch (e) {
    return { ok: false, status: 0, data: null, error: String(e) };
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok)
    return {
      ok: false,
      status: res.status,
      data: data as Costs,
      error: typeof data === "string" ? data : JSON.stringify(data, null, 2),
    };
  return { ok: true, status: res.status, data: data as Costs, error: null };
}

export default function CostsPage() {
  const [costs, setCosts] = useState<ApiResult<Costs> | null>(null);

  async function load() {
    setCosts(await fetchCosts());
  }
  useEffect(() => {
    void load();
  }, []);

  const c = costs?.ok ? costs.data : null;

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold">8. Costs</h1>
      <Section title="LLM cost roll-up — GET /internal/costs (via Next proxy)">
        <p className="mb-2 text-xs text-gray-600">
          Shared-secret guarded on the Python pipeline, so this goes through a
          server-side Next route (<code>/api/costs</code>) that holds the secret
          and resolves your account from the session.
        </p>
        <button
          onClick={load}
          className="mb-2 border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
        >
          Refresh
        </button>
        <ErrorBox result={costs} />
        {c && (
          <>
            <table className="mb-3 w-auto">
              <tbody>
                <tr>
                  <th>total cost (USD)</th>
                  <td>{c.cost_usd}</td>
                </tr>
                <tr>
                  <th>total calls</th>
                  <td>{c.calls}</td>
                </tr>
                <tr>
                  <th>mock calls</th>
                  <td>{c.mock_calls}</td>
                </tr>
                <tr>
                  <th>real calls</th>
                  <td className={c.real_calls === 0 ? "" : "bg-red-100"}>
                    {c.real_calls}
                  </td>
                </tr>
                <tr>
                  <th>total tokens</th>
                  <td>{c.total_tokens}</td>
                </tr>
                <tr>
                  <th>100% mock?</th>
                  <td>
                    {c.calls > 0 && c.real_calls === 0 ? "yes ✓" : "no / n/a"}
                  </td>
                </tr>
              </tbody>
            </table>

            <h3 className="mb-1 text-sm font-bold">Per model</h3>
            <table className="mb-2 w-full">
              <thead>
                <tr>
                  <th>provider</th>
                  <th>model</th>
                  <th>calls</th>
                  <th>cost (USD)</th>
                  <th>tokens</th>
                </tr>
              </thead>
              <tbody>
                {c.by_model.map((m, i) => (
                  <tr key={`${m.provider}-${m.model}-${i}`}>
                    <td>{m.provider}</td>
                    <td>{m.model}</td>
                    <td>{m.calls}</td>
                    <td>{m.cost_usd}</td>
                    <td>{m.total_tokens}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <Json data={costs?.data} />
      </Section>
    </div>
  );
}
