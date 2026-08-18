// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, postJSON } from "../../lib/api";
import {
  Button,
  Card,
  ErrorBox,
  PageHeader,
  RawJson,
} from "../../components/ui";

type Session = { userId: string; accountId: string } | null;

export default function LoginPage() {
  const router = useRouter();
  const [me, setMe] = useState<Session>(null);
  const [checked, setChecked] = useState(false);
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<{ status: number; error: string } | null>(null);

  const loadMe = useCallback(async () => {
    const r = await apiFetch<Session>("/auth/me");
    setMe(r.ok ? (r.data as Session) : null);
    setChecked(true);
  }, []);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  async function submit() {
    setBusy(true);
    setErr(null);
    const r =
      mode === "login"
        ? await postJSON<Session>("/auth/login", { email, password })
        : await postJSON<Session>("/auth/signup", {
            email,
            password,
            accountName: company,
          });
    setBusy(false);
    if (!r.ok) {
      setErr({ status: r.status, error: r.error ?? "" });
      return;
    }
    await loadMe();
    router.push("/setup");
  }

  async function logout() {
    await postJSON("/auth/logout", {});
    setMe(null);
  }

  return (
    <>
      <PageHeader
        title={me ? "Signed in" : "Sign in"}
        description={
          me
            ? "You're authenticated against the API."
            : "The demo account's password is printed by the seed job — run `docker compose logs seed`."
        }
      />

      {checked && me ? (
        <Card>
          <dl className="grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase text-gray-500">Account</dt>
              <dd className="font-mono text-sm">{me.accountId}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase text-gray-500">User</dt>
              <dd className="font-mono text-sm">{me.userId}</dd>
            </div>
          </dl>
          <div className="mt-4 flex gap-2">
            <Button onClick={() => router.push("/setup")}>Go to setup</Button>
            <Button variant="secondary" onClick={logout}>
              Sign out
            </Button>
          </div>
          <RawJson data={me} label="raw session JSON" />
        </Card>
      ) : (
        <Card className="max-w-md">
          <div className="mb-4 flex gap-2 text-sm">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`rounded px-2 py-1 ${mode === "login" ? "bg-gray-900 text-white" : "text-gray-600"}`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => setMode("signup")}
              className={`rounded px-2 py-1 ${mode === "signup" ? "bg-gray-900 text-white" : "text-gray-600"}`}
            >
              Create account
            </button>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className="space-y-3"
          >
            {mode === "signup" && (
              <Field
                label="Company"
                value={company}
                onChange={setCompany}
                placeholder="Acme Analytics"
              />
            )}
            <Field
              label="Email"
              type="email"
              value={email}
              onChange={setEmail}
              placeholder="owner@acme.example.com"
            />
            <Field
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
            />
            <Button type="submit" disabled={busy}>
              {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>

          {err && (
            <div className="mt-4">
              <ErrorBox
                status={err.status}
                error={err.error}
                context={mode === "login" ? "Sign-in failed" : "Sign-up failed"}
              />
            </div>
          )}
        </Card>
      )}
    </>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
        {label}
      </span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-gray-900 focus:outline-none"
      />
    </label>
  );
}
