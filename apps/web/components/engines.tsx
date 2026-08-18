// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Engine availability — honest status, never a key-entry form.
 *
 * Self-hosted keys belong in `.env`, not in a web form: a form implies the app
 * stores them, and an app that stores them is somewhere they can be read back.
 * So this panel only ever reports, and names the environment variable to set.
 *
 * It exists because the alternative is worse. A user with no keys who clicks
 * "run a scan" would otherwise watch it fail with a provider error, which reads
 * as a broken product rather than an unconfigured one.
 */
"use client";

import { useEffect, useState } from "react";
import { getJSON } from "../lib/api";
import { Badge, Card, ErrorBox, RawJson } from "./ui";

export type EngineStatus = {
  task: string;
  label: string;
  available: boolean;
  reason: string | null;
  missing_key_env: string | null;
  is_measurement: boolean;
};
type EnginesResponse = { mode: string; engines: EngineStatus[] };

export function useEngines() {
  const [data, setData] = useState<EnginesResponse | null>(null);
  const [err, setErr] = useState<{ status: number; error: string } | null>(null);

  useEffect(() => {
    (async () => {
      const res = await getJSON<EnginesResponse>("/engines");
      if (!res.ok) setErr({ status: res.status, error: res.error ?? "" });
      else setData(res.data);
    })();
  }, []);

  const measurement = (data?.engines ?? []).filter((e) => e.is_measurement);
  return {
    data,
    err,
    measurement,
    ready: measurement.filter((e) => e.available),
    mode: data?.mode,
  };
}

/** Compact one-liner for the top of a page that is about to spend money. */
export function EngineBanner() {
  const { data, err, measurement, ready, mode } = useEngines();
  if (err) return null; // the page's own error surface owns this
  if (!data) return null;

  if (mode === "mock") {
    return (
      <div className="mb-4 rounded-md border border-blue-300 bg-blue-50 p-3 text-sm text-blue-900">
        <Badge tone="info">mock mode</Badge>{" "}
        Scans run against canned fixtures — no API keys, no network, no cost. Set{" "}
        <code>GATEWAY_MODE=dev</code> in <code>.env</code> to measure real
        engines.
      </div>
    );
  }

  if (ready.length === 0) {
    const vars = [
      ...new Set(measurement.map((e) => e.missing_key_env).filter(Boolean)),
    ];
    return (
      <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
        <strong>No measurement engine is available.</strong> A scan cannot
        measure anything until you set one of{" "}
        {vars.map((v, i) => (
          <span key={v}>
            {i > 0 && ", "}
            <code>{v}</code>
          </span>
        ))}{" "}
        in <code>.env</code> and restart. See <code>docs/ENGINES.md</code> for
        cost and free-tier details.
      </div>
    );
  }

  return (
    <div className="mb-4 rounded-md border border-gray-200 bg-white p-3 text-sm text-gray-700">
      <Badge tone="good">
        {ready.length} of {measurement.length} engines ready
      </Badge>{" "}
      {ready.map((e) => e.label).join(", ")} — each active prompt costs 5
      grounded calls per engine, per scan.
    </div>
  );
}

/** Full table for the setup page. */
export function EnginePanel() {
  const { data, err, measurement, mode } = useEngines();

  if (err)
    return (
      <Card title="Engines">
        <ErrorBox
          status={err.status}
          error={err.error}
          context="Could not read engine status"
        />
      </Card>
    );
  if (!data)
    return (
      <Card title="Engines">
        <p className="text-sm text-gray-600">Checking…</p>
      </Card>
    );

  return (
    <Card
      title="Engines"
      description={`Gateway mode: ${mode}. Keys are read from .env — this page reports status, it never accepts them.`}
    >
      <ul className="space-y-2">
        {measurement.map((e) => (
          <li
            key={e.task}
            className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 pb-2 last:border-0"
          >
            <div className="min-w-0">
              <div className="font-mono text-sm text-gray-900">{e.label}</div>
              {!e.available && e.reason && (
                <div className="mt-0.5 text-xs text-gray-600">{e.reason}</div>
              )}
            </div>
            {e.available ? (
              <Badge tone="good">ready</Badge>
            ) : (
              <Badge tone="neutral">
                {e.missing_key_env ? `set ${e.missing_key_env}` : "unavailable"}
              </Badge>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-gray-500">
        Only Gemini has been verified against a live API. Perplexity, OpenAI and
        Claude are implemented against documented response shapes but unverified
        — see <span className="font-mono">docs/ENGINES.md</span>.
      </p>
      <RawJson data={data} label="raw engine JSON" />
    </Card>
  );
}
