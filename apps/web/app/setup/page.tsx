// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Onboarding: brand, competitors, prompts. Everything a new account needs
 * before its first scan, editable here.
 *
 * Two things on this page are load-bearing for a fresh signup:
 *
 *  1. THE DOMAIN. Diagnosis fetches `https://{domain}`; with no domain the
 *     whole stage is skipped and the user gets a scan that audited nothing,
 *     with no visible reason. So the field is prominent and its absence is
 *     called out rather than shown as an empty dash.
 *  2. PROMPT GENERATION (audit A4). A scan with no prompts measures nothing,
 *     and inventing 20 buyer-intent queries by hand is the single largest
 *     barrier for a new user. Safe to retry — the API dedupes.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, getJSON, postJSON } from "../../lib/api";
import {
  Badge,
  Button,
  Card,
  Cell,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  RawJson,
  Row,
  Table,
} from "../../components/ui";
import { EnginePanel } from "../../components/engines";

type Account = {
  id: string;
  name: string;
  domain: string | null;
  brandName: string | null;
  brandAliases: string[];
  settings?: { category?: string } | null;
};
type Prompt = {
  id: string;
  text: string;
  active: boolean;
  promptGroup?: string | null;
};
type Competitor = {
  id: string;
  name: string;
  domain?: string | null;
  isSelf: boolean;
};
type Err = { status: number; error: string; ctx: string };

export default function SetupPage() {
  const [account, setAccount] = useState<Account | null>(null);
  const [prompts, setPrompts] = useState<Prompt[] | null>(null);
  const [competitors, setCompetitors] = useState<Competitor[] | null>(null);
  const [err, setErr] = useState<Err | null>(null);
  const [loading, setLoading] = useState(true);

  // brand form
  const [brandName, setBrandName] = useState("");
  const [domain, setDomain] = useState("");
  const [aliases, setAliases] = useState("");
  const [category, setCategory] = useState("");
  const [savingBrand, setSavingBrand] = useState(false);
  const [savedBrand, setSavedBrand] = useState(false);

  // competitor form
  const [compName, setCompName] = useState("");
  const [compDomain, setCompDomain] = useState("");
  const [addingComp, setAddingComp] = useState(false);

  // prompts
  const [newPrompt, setNewPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genResult, setGenResult] = useState<{
    generated: number;
    created: number;
    skipped_duplicates: number;
  } | null>(null);

  const load = useCallback(async () => {
    const [a, p, c] = await Promise.all([
      getJSON<Account>("/account"),
      getJSON<Prompt[]>("/prompts"),
      getJSON<Competitor[]>("/competitors"),
    ]);
    if (!a.ok) {
      setErr({ status: a.status, error: a.error ?? "", ctx: "GET /account" });
      setLoading(false);
      return;
    }
    setAccount(a.data);
    setBrandName(a.data?.brandName ?? a.data?.name ?? "");
    setDomain(a.data?.domain ?? "");
    setAliases((a.data?.brandAliases ?? []).join(", "));
    setCategory(a.data?.settings?.category ?? "");
    setPrompts(p.ok ? (p.data ?? []) : []);
    setCompetitors(c.ok ? (c.data ?? []) : []);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function saveBrand() {
    setSavingBrand(true);
    setErr(null);
    setSavedBrand(false);
    const res = await apiFetch("/account", {
      method: "PATCH",
      body: JSON.stringify({
        brandName: brandName.trim() || null,
        // null clears it; "" is rejected by the API on purpose.
        domain: domain.trim() ? domain.trim() : null,
        brandAliases: aliases
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        // Drives prompt generation. Without it the generator falls back to
        // monitor.yaml's default_category and writes prompts about someone
        // else's industry — which is useless and not obviously wrong until you
        // read them.
        settings: category.trim() ? { category: category.trim() } : {},
      }),
    });
    setSavingBrand(false);
    if (!res.ok) {
      setErr({ status: res.status, error: res.error ?? "", ctx: "PATCH /account" });
      return;
    }
    setSavedBrand(true);
    load();
  }

  async function addCompetitor() {
    if (!compName.trim()) return;
    setAddingComp(true);
    setErr(null);
    const res = await postJSON("/competitors", {
      name: compName.trim(),
      ...(compDomain.trim() ? { domain: compDomain.trim() } : {}),
    });
    setAddingComp(false);
    if (!res.ok) {
      setErr({
        status: res.status,
        error: res.error ?? "",
        ctx: "POST /competitors",
      });
      return;
    }
    setCompName("");
    setCompDomain("");
    load();
  }

  async function removeCompetitor(id: string) {
    const res = await apiFetch(`/competitors/${id}`, { method: "DELETE" });
    if (!res.ok)
      setErr({
        status: res.status,
        error: res.error ?? "",
        ctx: `DELETE /competitors/${id}`,
      });
    load();
  }

  async function setPromptActive(id: string, active: boolean) {
    const res = await apiFetch(`/prompts/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ active }),
    });
    if (!res.ok)
      setErr({ status: res.status, error: res.error ?? "", ctx: "PATCH /prompts" });
    load();
  }

  async function removePrompt(id: string) {
    const res = await apiFetch(`/prompts/${id}`, { method: "DELETE" });
    if (!res.ok)
      setErr({ status: res.status, error: res.error ?? "", ctx: "DELETE /prompts" });
    load();
  }

  async function addPrompt() {
    if (newPrompt.trim().length < 5) return;
    const res = await postJSON("/prompts", { text: newPrompt.trim() });
    if (!res.ok) {
      setErr({ status: res.status, error: res.error ?? "", ctx: "POST /prompts" });
      return;
    }
    setNewPrompt("");
    load();
  }

  async function generatePrompts() {
    setGenerating(true);
    setErr(null);
    setGenResult(null);
    const res = await postJSON<{
      generated: number;
      created: number;
      skipped_duplicates: number;
    }>("/prompts/generate", {});
    setGenerating(false);
    if (!res.ok) {
      setErr({
        status: res.status,
        error: res.error ?? "",
        ctx: "POST /prompts/generate",
      });
      return;
    }
    setGenResult(res.data);
    load();
  }

  if (loading) return <Loading what="your account" />;

  const activePrompts = (prompts ?? []).filter((p) => p.active).length;
  const ready = Boolean(account?.domain) && activePrompts > 0;

  return (
    <>
      <PageHeader
        title="Setup"
        description="What we measure, and who we measure you against."
      />

      {err && (
        <div className="mb-4">
          <ErrorBox status={err.status} error={err.error} context={err.ctx} />
          {err.status === 503 && (
            <p className="mt-2 text-sm text-gray-700">
              The generation engine has no API key in this deployment. Add one to{" "}
              <code>.env</code> and restart, or add prompts by hand below.
            </p>
          )}
        </div>
      )}

      {/* A new account has neither, and a scan without them silently does
          nothing useful. Say so before they run one. */}
      {!ready && (
        <div className="mb-6 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <strong>Finish setup before your first scan.</strong>
          <ul className="mt-1 list-inside list-disc">
            {!account?.domain && (
              <li>
                Set your <strong>domain</strong> — without it the site audit is
                skipped entirely.
              </li>
            )}
            {activePrompts === 0 && (
              <li>
                Add at least one <strong>prompt</strong> — a scan with no prompts
                measures nothing.
              </li>
            )}
          </ul>
        </div>
      )}

      <Card title="Brand" className="mb-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Brand name" value={brandName} onChange={setBrandName} />
          <Field
            label="Domain"
            value={domain}
            onChange={setDomain}
            placeholder="example.com"
            hint="No scheme needed — a pasted URL is trimmed."
          />
          <Field
            label="Aliases (comma separated)"
            value={aliases}
            onChange={setAliases}
            placeholder="Acme, AcmeAI"
            hint="Other spellings engines might use."
          />
          <Field
            label="Category"
            value={category}
            onChange={setCategory}
            placeholder="AI image and video generation"
            hint="What market you're in. Prompt generation uses this — leave it blank and you get prompts about the wrong industry."
          />
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={saveBrand} disabled={savingBrand}>
            {savingBrand ? "Saving…" : "Save brand"}
          </Button>
          {savedBrand && <span className="text-sm text-green-700">Saved.</span>}
        </div>
      </Card>

      <div className="mb-4">
        <EnginePanel />
      </div>

      <Card
        title="Prompts"
        description="The buyer-intent questions we ask the engines. These are what get measured."
        className="mb-4"
      >
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Button onClick={generatePrompts} disabled={generating}>
            {generating ? "Generating…" : "Generate prompts"}
          </Button>
          <span className="text-xs text-gray-500">
            One model call. Safe to run twice — duplicates are skipped.
          </span>
        </div>

        {genResult && (
          <div className="mb-3 rounded border border-green-300 bg-green-50 p-2 text-sm text-green-900">
            Generated {genResult.generated}, added {genResult.created}
            {genResult.skipped_duplicates > 0 &&
              `, skipped ${genResult.skipped_duplicates} duplicate(s)`}
            .
          </div>
        )}

        <div className="mb-4 flex gap-2">
          <input
            value={newPrompt}
            onChange={(e) => setNewPrompt(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addPrompt()}
            placeholder="e.g. best AI image generator for marketing teams"
            className="flex-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-900 focus:outline-none"
          />
          <Button variant="secondary" onClick={addPrompt}>
            Add
          </Button>
        </div>

        {prompts && prompts.length === 0 ? (
          <Empty title="No prompts yet">
            Generate a set above, or add the questions your buyers actually ask
            an AI assistant.
          </Empty>
        ) : (
          <>
            <Table head={["Prompt", "Source", "Active", ""]}>
              {(prompts ?? []).map((p) => (
                <Row key={p.id}>
                  <Cell>{p.text}</Cell>
                  <Cell>
                    <Badge tone={p.promptGroup === "auto" ? "info" : "neutral"}>
                      {p.promptGroup === "auto" ? "generated" : "manual"}
                    </Badge>
                  </Cell>
                  <Cell>
                    {/* Turning a prompt off is the main cost lever: every
                        active prompt is `repeats` grounded calls per engine. */}
                    <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs">
                      <input
                        type="checkbox"
                        checked={p.active}
                        onChange={(e) => setPromptActive(p.id, e.target.checked)}
                      />
                      {p.active ? "active" : "off"}
                    </label>
                  </Cell>
                  <Cell>
                    <button
                      type="button"
                      onClick={() => removePrompt(p.id)}
                      className="text-xs text-red-700 underline"
                    >
                      remove
                    </button>
                  </Cell>
                </Row>
              ))}
            </Table>
            <p className="mt-3 text-xs text-gray-500">
              <strong>{activePrompts} active prompt(s) = {activePrompts * 5}{" "}
              grounded calls per engine per scan</strong> (5 repeats each).
              Gemini&rsquo;s free tier is about 20 calls/day, so keep this at 4
              or fewer to stay inside it. Turn prompts off above to reduce it.
            </p>
            <RawJson data={prompts} label="raw prompts JSON" />
          </>
        )}
      </Card>

      <Card
        title="Competitors"
        description="Tracked rivals. Brands the engines name that aren't listed here appear as 'discovered' on the leaderboard."
      >
        <div className="mb-4 flex flex-wrap gap-2">
          <input
            value={compName}
            onChange={(e) => setCompName(e.target.value)}
            placeholder="Competitor name"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-900 focus:outline-none"
          />
          <input
            value={compDomain}
            onChange={(e) => setCompDomain(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addCompetitor()}
            placeholder="domain.com (optional)"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-900 focus:outline-none"
          />
          <Button variant="secondary" onClick={addCompetitor} disabled={addingComp}>
            {addingComp ? "Adding…" : "Add competitor"}
          </Button>
        </div>

        {competitors && competitors.length === 0 ? (
          <Empty title="No competitors configured">
            Not required — the leaderboard still surfaces whoever the engines
            name.
          </Empty>
        ) : (
          <Table head={["Name", "Domain", "", ""]}>
            {(competitors ?? []).map((c) => (
              <Row key={c.id}>
                <Cell>{c.name}</Cell>
                <Cell className="text-gray-600">{c.domain ?? "—"}</Cell>
                <Cell>{c.isSelf && <Badge tone="info">you</Badge>}</Cell>
                <Cell>
                  {!c.isSelf && (
                    <button
                      type="button"
                      onClick={() => removeCompetitor(c.id)}
                      className="text-xs text-red-700 underline"
                    >
                      remove
                    </button>
                  )}
                </Cell>
              </Row>
            ))}
          </Table>
        )}
      </Card>

      <p className="mt-6 text-sm text-gray-600">
        {ready ? (
          <>
            Ready.{" "}
            <Link href="/scans" className="font-medium text-blue-700 underline">
              Run a scan
            </Link>
            .
          </>
        ) : (
          <>Finish the steps above, then run a scan.</>
        )}
      </p>
    </>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
        {label}
      </span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-900 focus:outline-none"
      />
      {hint && <span className="mt-1 block text-xs text-gray-500">{hint}</span>}
    </label>
  );
}
