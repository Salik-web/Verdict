// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
// Thin fetch wrapper around the real TS API. Every call sends the httpOnly
// session cookie (credentials: "include") and NEVER swallows errors — a non-2xx
// returns { ok:false, status, data } so screens can print the status + body.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3000";

export type ApiResult<T = unknown> = {
  ok: boolean;
  status: number;
  data: T | null;
  // Human-readable error (status line + body) when ok === false; null otherwise.
  error: string | null;
};

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  const hasBody = init.body != null;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        ...(hasBody ? { "content-type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch (e) {
    // Network/CORS failures never reach a status code — surface them loudly.
    return {
      ok: false,
      status: 0,
      data: null,
      error:
        `network/CORS error calling ${API_BASE}${path}: ${String(e)}\n` +
        `Is the API running? Is its FRONTEND_ORIGIN set to this app's origin ` +
        `(http://localhost:5173)?`,
    };
  }

  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text; // non-JSON body (e.g. an HTML error page) — keep it visible
  }

  if (!res.ok) {
    const body =
      typeof data === "string" ? data : JSON.stringify(data, null, 2);
    return { ok: false, status: res.status, data: data as T, error: body };
  }
  return { ok: true, status: res.status, data: data as T, error: null };
}

// Convenience helpers.
export const getJSON = <T = unknown>(path: string) => apiFetch<T>(path);

export const postJSON = <T = unknown>(path: string, body: unknown) =>
  apiFetch<T>(path, { method: "POST", body: JSON.stringify(body) });

export const del = <T = unknown>(path: string) =>
  apiFetch<T>(path, { method: "DELETE" });
