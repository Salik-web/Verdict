"use client";

import { useEffect, useState } from "react";
import { apiFetch, type ApiResult } from "@/lib/api";
import { ErrorBox, Json, Section } from "@/lib/ui";

type Asset = Record<string, unknown> & {
  id: string;
  type: string;
  title: string | null;
  status: string;
  validationState: string;
  targetPromptIds: string[];
  contentRef: string | null;
};

type AssetDetail = Asset & {
  content: string | null;
  contentError: string | null;
};

export default function AssetsPage() {
  const [list, setList] = useState<ApiResult<Asset[]> | null>(null);
  const [detail, setDetail] = useState<ApiResult<AssetDetail> | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  async function load() {
    setList(await apiFetch<Asset[]>("/assets?limit=500"));
  }
  useEffect(() => {
    void load();
  }, []);

  async function view(id: string) {
    setOpenId(id);
    setDetail(await apiFetch<AssetDetail>(`/assets/${id}`));
  }

  const content = detail?.ok ? detail.data?.content : null;

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold">6. Assets</h1>

      <Section title="Generated assets — GET /assets">
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
              <th>type</th>
              <th>title</th>
              <th>status</th>
              <th>validationState</th>
              <th>targetPromptIds</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(list?.data ?? []).map((a) => (
              <tr key={a.id}>
                <td>{a.type}</td>
                <td>{a.title ?? "—"}</td>
                <td>{a.status}</td>
                <td>{a.validationState}</td>
                <td>{(a.targetPromptIds ?? []).length}</td>
                <td>
                  <button
                    onClick={() => view(a.id)}
                    className="text-blue-700 underline"
                  >
                    view content
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(list?.data?.length ?? 0) === 0 && list?.ok && (
          <p className="text-sm text-gray-600">
            No assets. NOTE: assets come from the Execution stage, which has no
            API trigger — see the harness README &quot;orchestration&quot;
            finding.
          </p>
        )}
        <Json data={list?.data} />
      </Section>

      {openId && (
        <Section title={`Asset content — GET /assets/${openId}`}>
          <ErrorBox result={detail} />
          {detail?.data?.contentError && (
            <p className="text-sm text-red-800">
              contentError: {detail.data.contentError}
            </p>
          )}
          {content ? (
            <>
              <p className="mb-1 text-xs text-gray-600">
                Rendered in a locked-down sandboxed iframe (no scripts,
                same-origin blocked). HTML is nh3-sanitized server-side.
              </p>
              <iframe
                title="asset content"
                sandbox=""
                srcDoc={content}
                className="h-96 w-full border border-gray-400"
              />
            </>
          ) : (
            detail?.ok && (
              <p className="text-sm text-gray-600">
                No content (contentRef empty or file missing).
              </p>
            )
          )}
          <Json data={detail?.data} />
        </Section>
      )}
    </div>
  );
}
