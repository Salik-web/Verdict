// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Shared UI primitives.
 *
 * Deliberately small and boring: default Tailwind palette, light mode only, no
 * component library, no animation. The bar is "a competent developer would
 * trust this", not "a designer made this".
 *
 * Three of these carry product meaning rather than styling, and should not be
 * simplified away:
 *
 *   ErrorBox  — prints the real HTTP status AND body. An open-source user
 *               debugging their own deployment needs the actual response, not
 *               "something went wrong".
 *   RawJson   — every data view can show its underlying JSON. This is what
 *               makes a screen auditable instead of asking for trust.
 *   Verdict   — renders no_change / inconclusive exactly as plainly as
 *               improved. A UI that makes good news louder than honest news is
 *               lying by typography.
 */
"use client";

import { useState } from "react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-gray-200 pb-4">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
        {description && (
          <p className="mt-1 max-w-2xl text-sm text-gray-600">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({
  title,
  description,
  children,
  className = "",
}: {
  title?: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-md border border-gray-200 bg-white ${className}`}
    >
      {(title || description) && (
        <div className="border-b border-gray-200 px-4 py-3">
          {title && (
            <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
          )}
          {description && (
            <p className="mt-0.5 text-sm text-gray-600">{description}</p>
          )}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-gray-200 bg-white px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-gray-900">
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-gray-500">{hint}</div>}
    </div>
  );
}

type Tone = "neutral" | "good" | "warn" | "bad" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-gray-100 text-gray-700 border-gray-300",
  good: "bg-green-50 text-green-800 border-green-300",
  warn: "bg-amber-50 text-amber-800 border-amber-300",
  bad: "bg-red-50 text-red-800 border-red-300",
  info: "bg-blue-50 text-blue-800 border-blue-300",
};

export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

/** HTTP status, coloured by class. 2xx green, 3xx blue, 4xx amber, 5xx red. */
export function HttpStatus({ status }: { status: number | null | undefined }) {
  if (status == null) return <Badge tone="bad">no response</Badge>;
  const tone: Tone =
    status < 300
      ? "good"
      : status < 400
        ? "info"
        : status < 500
          ? "warn"
          : "bad";
  return <Badge tone={tone}>HTTP {status}</Badge>;
}

export function Button({
  children,
  onClick,
  disabled,
  type = "button",
  variant = "primary",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  variant?: "primary" | "secondary";
}) {
  const base =
    "rounded-md border px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50";
  const styles =
    variant === "primary"
      ? "border-gray-900 bg-gray-900 text-white hover:bg-gray-700"
      : "border-gray-300 bg-white text-gray-800 hover:bg-gray-50";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${styles}`}
    >
      {children}
    </button>
  );
}

/** The real status line and body. Never paraphrase an error into prose. */
export function ErrorBox({
  status,
  error,
  context,
}: {
  status?: number;
  error: string;
  context?: string;
}) {
  return (
    <div className="rounded-md border border-red-300 bg-red-50 p-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold text-red-800">
          {context ?? "Request failed"}
        </span>
        {status != null && (
          <Badge tone="bad">{status === 0 ? "network error" : `HTTP ${status}`}</Badge>
        )}
      </div>
      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs text-red-900">
        {error}
      </pre>
    </div>
  );
}

export function Loading({ what = "data" }: { what?: string }) {
  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 p-6 text-center">
      <p className="text-sm text-gray-600">Loading {what}…</p>
    </div>
  );
}

/**
 * Empty states are load-bearing here: a fresh account has no data for every
 * screen, and a scan takes minutes. "Nothing yet" plus what to do about it is
 * the difference between a working product and a broken-looking one.
 */
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-dashed border-gray-300 bg-gray-50 p-8 text-center">
      <p className="text-sm font-medium text-gray-800">{title}</p>
      {children && <div className="mt-2 text-sm text-gray-600">{children}</div>}
    </div>
  );
}

export function RawJson({ data, label = "raw JSON" }: { data: unknown; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="text-xs text-gray-500 underline hover:text-gray-800"
      >
        {open ? "hide" : "show"} {label}
      </button>
      {open && (
        <pre className="mt-2 max-h-96 overflow-auto rounded border border-gray-200 bg-gray-50 p-3 text-xs text-gray-800">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function Table({
  head,
  children,
}: {
  head: React.ReactNode[];
  children: React.ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left">
            {head.map((h, i) => (
              <th
                key={i}
                className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Row({
  children,
  highlight = false,
}: {
  children: React.ReactNode;
  highlight?: boolean;
}) {
  return (
    <tr
      className={`border-b border-gray-100 ${highlight ? "bg-blue-50" : "hover:bg-gray-50"}`}
    >
      {children}
    </tr>
  );
}

export function Cell({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={`px-3 py-2 align-top ${className}`}>{children}</td>;
}

/**
 * A verification verdict. `no_change` and `inconclusive` get the same visual
 * weight as `improved` — they are first-class results, and a scan that could
 * not prove anything must not look like a failure or be quietly de-emphasised.
 */
export function Verdict({ verdict }: { verdict: string }) {
  const tone: Tone =
    verdict === "improved"
      ? "good"
      : verdict === "regressed"
        ? "bad"
        : "neutral";
  return <Badge tone={tone}>{verdict.replace("_", " ")}</Badge>;
}

export function pct(n: number | string | null | undefined): string {
  const v = typeof n === "string" ? Number(n) : n;
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

export function money(n: number | string | null | undefined, digits = 4): string {
  const v = typeof n === "string" ? Number(n) : n;
  if (v == null || Number.isNaN(v)) return "—";
  return `$${v.toFixed(digits)}`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleString();
}
