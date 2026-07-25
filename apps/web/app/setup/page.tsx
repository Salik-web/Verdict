"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, del, postJSON, type ApiResult } from "@/lib/api";
import { ErrorBox, Json, Section } from "@/lib/ui";

type Row = Record<string, unknown>;

export default function SetupPage() {
  return (
    <div>
      <h1 className="mb-1 text-xl font-bold">2. Setup</h1>
      <p className="mb-4 text-xs text-gray-600">
        Everything on one page. Log in first (Screen 1). A scan needs at least one
        active prompt.
      </p>
      <AccountSection />
      <CompetitorsSection />
      <PromptsSection />
      <VerifiedFactsSection />
      <RunScanSection />
    </div>
  );
}

// ── Account ──────────────────────────────────────────────────────────────
function AccountSection() {
  const [acct, setAcct] = useState<ApiResult | null>(null);
  const [brandName, setBrandName] = useState("");
  const [domain, setDomain] = useState("");
  const [saved, setSaved] = useState<ApiResult | null>(null);

  async function load() {
    const r = await apiFetch("/account");
    setAcct(r);
    if (r.ok) {
      const d = r.data as Row;
      setBrandName((d.brandName as string) ?? "");
      setDomain((d.domain as string) ?? "");
    }
  }
  useEffect(() => {
    void load();
  }, []);

  async function save() {
    const r = await apiFetch("/account", {
      method: "PATCH",
      body: JSON.stringify({ brandName, domain }),
    });
    setSaved(r);
    if (r.ok) void load();
  }

  return (
    <Section title="Account / company — GET + PATCH /account">
      <div className="mb-2 flex flex-col gap-2 sm:max-w-lg">
        <label className="text-sm">
          Brand name
          <input
            className="ml-2 w-72"
            value={brandName}
            onChange={(e) => setBrandName(e.target.value)}
            placeholder="Acme Analytics"
          />
        </label>
        <label className="text-sm">
          Domain
          <input
            className="ml-2 w-72"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="acme.example.com"
          />
        </label>
        <button
          onClick={save}
          className="w-32 border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
        >
          Save account
        </button>
      </div>
      <ErrorBox result={acct} />
      <ErrorBox result={saved} />
      <Json data={acct?.data} />
    </Section>
  );
}

// ── Competitors ──────────────────────────────────────────────────────────
function CompetitorsSection() {
  const [list, setList] = useState<ApiResult<Row[]> | null>(null);
  const [name, setName] = useState("Globex Insights");
  const [domain, setDomain] = useState("globex.example.com");
  const [isSelf, setIsSelf] = useState(false);
  const [action, setAction] = useState<ApiResult | null>(null);

  async function load() {
    setList(await apiFetch<Row[]>("/competitors"));
  }
  useEffect(() => {
    void load();
  }, []);

  async function add() {
    const r = await postJSON("/competitors", {
      name,
      domain: domain || undefined,
      isSelf,
    });
    setAction(r);
    if (r.ok) void load();
  }
  async function remove(id: string) {
    const r = await del(`/competitors/${id}`);
    setAction(r);
    void load();
  }

  return (
    <Section title="Competitors — GET / POST / DELETE /competitors">
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          Name
          <input
            className="ml-1 w-48"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="text-sm">
          Domain
          <input
            className="ml-1 w-48"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
          />
        </label>
        <label className="text-sm">
          <input
            type="checkbox"
            className="mr-1"
            checked={isSelf}
            onChange={(e) => setIsSelf(e.target.checked)}
          />
          isSelf
        </label>
        <button
          onClick={add}
          className="border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
        >
          Add competitor
        </button>
      </div>
      <ErrorBox result={action} />
      <ErrorBox result={list} />
      <table className="mb-2 w-full">
        <thead>
          <tr>
            <th>name</th>
            <th>domain</th>
            <th>isSelf</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(list?.data ?? []).map((c) => (
            <tr key={c.id as string}>
              <td>{c.name as string}</td>
              <td>{(c.domain as string) ?? ""}</td>
              <td>{String(c.isSelf)}</td>
              <td>
                <button
                  onClick={() => remove(c.id as string)}
                  className="text-red-700 underline"
                >
                  delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Json data={list?.data} />
    </Section>
  );
}

// ── Prompts ──────────────────────────────────────────────────────────────
function PromptsSection() {
  const [list, setList] = useState<ApiResult<Row[]> | null>(null);
  const [text, setText] = useState("What's the best product analytics tool for B2B SaaS?");
  const [category, setCategory] = useState("comparison");
  const [action, setAction] = useState<ApiResult | null>(null);

  async function load() {
    setList(await apiFetch<Row[]>("/prompts"));
  }
  useEffect(() => {
    void load();
  }, []);

  async function add() {
    const r = await postJSON("/prompts", {
      text,
      category: category || undefined,
    });
    setAction(r);
    if (r.ok) void load();
  }
  async function remove(id: string) {
    const r = await del(`/prompts/${id}`);
    setAction(r);
    void load();
  }

  return (
    <Section title="Prompts — GET / POST / DELETE /prompts">
      <p className="mb-2 text-xs text-gray-600">
        NOTE: the API has no prompt auto-generation endpoint and signup seeds
        none, so a fresh account starts with an empty list. Add prompts manually
        here — a scan needs ≥ 1 active prompt.
      </p>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          Text
          <input
            className="ml-1 w-96"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <label className="text-sm">
          Category
          <input
            className="ml-1 w-40"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
        </label>
        <button
          onClick={add}
          className="border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
        >
          Add prompt
        </button>
      </div>
      <p className="mb-1 text-xs">count: {list?.data?.length ?? 0}</p>
      <ErrorBox result={action} />
      <ErrorBox result={list} />
      <table className="mb-2 w-full">
        <thead>
          <tr>
            <th>text</th>
            <th>category</th>
            <th>active</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(list?.data ?? []).map((p) => (
            <tr key={p.id as string}>
              <td>{p.text as string}</td>
              <td>{(p.category as string) ?? ""}</td>
              <td>{String(p.active)}</td>
              <td>
                <button
                  onClick={() => remove(p.id as string)}
                  className="text-red-700 underline"
                >
                  delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Json data={list?.data} />
    </Section>
  );
}

// ── Verified facts ───────────────────────────────────────────────────────
function VerifiedFactsSection() {
  const [list, setList] = useState<ApiResult<Row[]> | null>(null);
  const [factType, setFactType] = useState("pricing");
  const [key, setKey] = useState("starting_price");
  const [valueStr, setValueStr] = useState('{"display":"$0, usage-based"}');
  const [action, setAction] = useState<ApiResult | null>(null);

  async function load() {
    setList(await apiFetch<Row[]>("/verified-facts"));
  }
  useEffect(() => {
    void load();
  }, []);

  async function add() {
    // value is jsonb: try to parse as JSON, else send the raw string.
    let value: unknown = valueStr;
    try {
      value = JSON.parse(valueStr);
    } catch {
      /* keep as string */
    }
    const r = await postJSON("/verified-facts", { factType, key, value });
    setAction(r);
    if (r.ok) void load();
  }

  return (
    <Section title="Verified facts — GET / POST /verified-facts">
      <p className="mb-2 text-xs text-gray-600">
        The comparison-page generator reads <code>value.display</code>, so a
        useful value is JSON like <code>{'{"display":"..."}'}</code>.
      </p>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          fact_type
          <input
            className="ml-1 w-32"
            value={factType}
            onChange={(e) => setFactType(e.target.value)}
          />
        </label>
        <label className="text-sm">
          key
          <input
            className="ml-1 w-40"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
        </label>
        <label className="text-sm">
          value (JSON)
          <input
            className="ml-1 w-72"
            value={valueStr}
            onChange={(e) => setValueStr(e.target.value)}
          />
        </label>
        <button
          onClick={add}
          className="border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
        >
          Add fact
        </button>
      </div>
      <ErrorBox result={action} />
      <ErrorBox result={list} />
      <table className="mb-2 w-full">
        <thead>
          <tr>
            <th>fact_type</th>
            <th>key</th>
            <th>value</th>
            <th>active</th>
          </tr>
        </thead>
        <tbody>
          {(list?.data ?? []).map((f) => (
            <tr key={f.id as string}>
              <td>{f.factType as string}</td>
              <td>{f.key as string}</td>
              <td>{JSON.stringify(f.value)}</td>
              <td>{String(f.isActive)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Json data={list?.data} />
    </Section>
  );
}

// ── Run scan ─────────────────────────────────────────────────────────────
function RunScanSection() {
  const [result, setResult] = useState<ApiResult<Row> | null>(null);

  async function run() {
    // engines defaults to ["all"] server-side; the pipeline uses its configured
    // engines regardless. Requires the Python pipeline to be running (else 502).
    setResult(await postJSON<Row>("/scans", {}));
  }

  const scanId = result?.ok ? (result.data?.scanId as string) : null;

  return (
    <Section title="Run scan — POST /scans">
      <button
        onClick={run}
        className="mb-2 border border-gray-500 bg-blue-200 px-3 py-1 text-sm font-bold"
      >
        Run scan
      </button>
      {scanId && (
        <p className="text-sm">
          Scan created: <code>{scanId}</code> →{" "}
          <Link href="/scans" className="text-blue-700 underline">
            watch it on Scans
          </Link>
        </p>
      )}
      <ErrorBox result={result} />
      {result?.ok && <Json data={result.data} />}
    </Section>
  );
}
