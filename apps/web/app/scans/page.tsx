"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch, type ApiResult } from "@/lib/api";
import { ErrorBox, Json, Section } from "@/lib/ui";

type Scan = Record<string, unknown> & { id: string; status: string };

const TERMINAL = new Set(["completed", "failed", "canceled"]);

export default function ScansPage() {
  const [list, setList] = useState<ApiResult<Scan[]> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ApiResult<Scan> | null>(null);
  const [polling, setPolling] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function loadList() {
    setList(await apiFetch<Scan[]>("/scans"));
  }
  useEffect(() => {
    void loadList();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  // Poll a single scan until it reaches a terminal status.
  async function pollOnce(id: string) {
    const r = await apiFetch<Scan>(`/scans/${id}`);
    setDetail(r);
    const status = r.ok ? r.data?.status : undefined;
    if (r.ok && status && !TERMINAL.has(status)) {
      timer.current = setTimeout(() => void pollOnce(id), 1500);
    } else {
      setPolling(false);
      void loadList(); // refresh the list's statuses when done
    }
  }

  function select(id: string) {
    if (timer.current) clearTimeout(timer.current);
    setSelectedId(id);
    setPolling(true);
    void pollOnce(id);
  }

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold">3. Scans</h1>

      <Section title="All scans — GET /scans">
        <button
          onClick={loadList}
          className="mb-2 border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
        >
          Refresh
        </button>
        <ErrorBox result={list} />
        <table className="mb-2 w-full">
          <thead>
            <tr>
              <th>id</th>
              <th>status</th>
              <th>triggeredBy</th>
              <th>createdAt</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(list?.data ?? []).map((s) => (
              <tr
                key={s.id}
                className={s.id === selectedId ? "bg-yellow-100" : ""}
              >
                <td className="font-mono text-xs">{s.id}</td>
                <td>{s.status}</td>
                <td className="font-mono text-xs">
                  {(s.triggeredBy as string) ?? ""}
                </td>
                <td className="text-xs">{s.createdAt as string}</td>
                <td>
                  <button
                    onClick={() => select(s.id)}
                    className="text-blue-700 underline"
                  >
                    poll
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(list?.data?.length ?? 0) === 0 && list?.ok && (
          <p className="text-sm text-gray-600">
            No scans yet — run one from Setup.
          </p>
        )}
        <Json data={list?.data} />
      </Section>

      {selectedId && (
        <Section title={`Scan detail — GET /scans/${selectedId}`}>
          <p className="mb-2 text-sm">
            {polling ? (
              <span className="text-blue-700">polling every 1.5s…</span>
            ) : (
              <span className="text-green-700">
                stopped (terminal status or error)
              </span>
            )}{" "}
            status: <b>{detail?.ok ? detail.data?.status : "?"}</b>
          </p>
          <ErrorBox result={detail} />
          <Json data={detail?.data} />
        </Section>
      )}
    </div>
  );
}
