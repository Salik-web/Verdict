// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Auth + tenant-isolation plugin.
 *
 * `requireAuth` resolves the session cookie -> {userId, accountId} and attaches
 * it to the request. Every downstream handler takes account_id from HERE (the
 * session), never from the URL or body — so a user can only ever touch rows of
 * their own tenant, and resource lookups are (accountId, id) pairs (no IDOR).
 */
import type { FastifyReply, FastifyRequest } from "fastify";
import type { SessionStore } from "./session-store.js";

export interface AuthContext {
  userId: string;
  accountId: string;
}

declare module "fastify" {
  interface FastifyRequest {
    auth: AuthContext | null;
  }
}

export const SESSION_COOKIE = "geo_session";
export const REFRESH_COOKIE = "geo_refresh";

export const cookieBaseOptions = {
  httpOnly: true,
  sameSite: "lax",
  secure: process.env.NODE_ENV === "production",
  path: "/",
  signed: true,
} as const;

export function buildRequireAuth(sessions: SessionStore) {
  return async function requireAuth(
    req: FastifyRequest,
    reply: FastifyReply,
  ): Promise<void> {
    req.auth = null;
    const raw = req.cookies[SESSION_COOKIE];
    if (raw) {
      const unsigned = req.unsignCookie(raw);
      if (unsigned.valid && unsigned.value) {
        const session = await sessions.getSession(unsigned.value);
        if (session) {
          req.auth = { userId: session.userId, accountId: session.accountId };
          return;
        }
      }
    }
    await reply.code(401).send({ error: "unauthorized" });
  };
}

/** Narrows req.auth for handlers behind requireAuth. */
export function authOf(req: FastifyRequest): AuthContext {
  if (!req.auth)
    throw new Error("handler reached without auth — check preHandler");
  return req.auth;
}
