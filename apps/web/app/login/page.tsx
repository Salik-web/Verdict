"use client";

import { useEffect, useState } from "react";
import { apiFetch, postJSON, type ApiResult } from "@/lib/api";
import { ErrorBox, Json, Section } from "@/lib/ui";

export default function LoginPage() {
  const [me, setMe] = useState<ApiResult | null>(null);

  // Signup form
  const [suEmail, setSuEmail] = useState("founder@example.com");
  const [suPass, setSuPass] = useState("supersecret123");
  const [suCompany, setSuCompany] = useState("Acme Analytics");
  const [suResult, setSuResult] = useState<ApiResult | null>(null);

  // Login form
  const [liEmail, setLiEmail] = useState("founder@example.com");
  const [liPass, setLiPass] = useState("supersecret123");
  const [liResult, setLiResult] = useState<ApiResult | null>(null);

  async function loadMe() {
    setMe(await apiFetch("/auth/me"));
  }
  useEffect(() => {
    void loadMe();
  }, []);

  async function signup() {
    const r = await postJSON("/auth/signup", {
      email: suEmail,
      password: suPass,
      accountName: suCompany,
    });
    setSuResult(r);
    if (r.ok) void loadMe();
  }

  async function login() {
    const r = await postJSON("/auth/login", { email: liEmail, password: liPass });
    setLiResult(r);
    if (r.ok) void loadMe();
  }

  async function logout() {
    await postJSON("/auth/logout", {});
    void loadMe();
  }

  return (
    <div>
      <h1 className="mb-4 text-xl font-bold">1. Login</h1>

      <Section title="Current identity — GET /auth/me">
        <div className="mb-2 flex gap-2">
          <button
            onClick={loadMe}
            className="border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
          >
            Refresh /auth/me
          </button>
          <button
            onClick={logout}
            className="border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
          >
            Logout
          </button>
        </div>
        {me?.ok ? (
          <p className="text-sm">
            Logged in as <b>{(me.data as { email?: string })?.email}</b> · account{" "}
            <code>{(me.data as { accountId?: string })?.accountId}</code>
          </p>
        ) : (
          <p className="text-sm text-gray-600">Not logged in (or session expired).</p>
        )}
        <ErrorBox result={me} />
        <Json data={me?.data} />
      </Section>

      <Section title="Sign up — POST /auth/signup">
        <p className="mb-2 text-xs text-gray-600">
          Password must be ≥ 10 chars. A fresh account starts empty (no prompts /
          competitors / facts) — you add those on Setup.
        </p>
        <div className="flex flex-col gap-2 sm:max-w-md">
          <label className="text-sm">
            Email
            <input
              className="ml-2 w-64"
              value={suEmail}
              onChange={(e) => setSuEmail(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Password
            <input
              className="ml-2 w-64"
              value={suPass}
              onChange={(e) => setSuPass(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Company
            <input
              className="ml-2 w-64"
              value={suCompany}
              onChange={(e) => setSuCompany(e.target.value)}
            />
          </label>
          <button
            onClick={signup}
            className="w-32 border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
          >
            Sign up
          </button>
        </div>
        <ErrorBox result={suResult} />
        {suResult?.ok && <Json data={suResult.data} />}
      </Section>

      <Section title="Log in — POST /auth/login">
        <div className="flex flex-col gap-2 sm:max-w-md">
          <label className="text-sm">
            Email
            <input
              className="ml-2 w-64"
              value={liEmail}
              onChange={(e) => setLiEmail(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Password
            <input
              className="ml-2 w-64"
              value={liPass}
              onChange={(e) => setLiPass(e.target.value)}
            />
          </label>
          <button
            onClick={login}
            className="w-32 border border-gray-500 bg-gray-200 px-2 py-1 text-sm"
          >
            Log in
          </button>
        </div>
        <ErrorBox result={liResult} />
        {liResult?.ok && <Json data={liResult.data} />}
      </Section>
    </div>
  );
}
