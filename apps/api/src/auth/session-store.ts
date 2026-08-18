// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Redis-backed sessions with refresh-token rotation and reuse detection.
 *
 * Design: opaque random ids in httpOnly cookies; server state in Redis.
 *   session:<id>  -> {userId, accountId, familyId}      TTL = SESSION_TTL_S
 *   refresh:<id>  -> {userId, accountId, familyId}      TTL = REFRESH_TTL_S
 *   family:<id>   -> "1" while the token family is valid
 *
 * Rotation: each /auth/refresh atomically consumes the refresh token (GETDEL)
 * and issues a new session + refresh pair in the same family. If a refresh
 * token is presented twice (theft indicator), the whole family is revoked —
 * both the attacker's and the victim's tokens die.
 *
 * Sessions are deliberately in Redis, not Postgres: they're ephemeral,
 * single-service state — not part of the cross-service schema contract.
 */
import { randomBytes } from "node:crypto";
import type { Redis } from "ioredis";

export interface SessionData {
  userId: string;
  accountId: string;
  familyId: string;
}

export interface SessionPair {
  sessionId: string;
  refreshId: string;
}

const sKey = (id: string) => `session:${id}`;
const rKey = (id: string) => `refresh:${id}`;
const fKey = (id: string) => `family:${id}`;

function newId(): string {
  return randomBytes(32).toString("base64url");
}

export class SessionStore {
  constructor(
    private readonly redis: Redis,
    private readonly sessionTtlS: number,
    private readonly refreshTtlS: number,
  ) {}

  /** Creates a brand-new session family (login). */
  async create(userId: string, accountId: string): Promise<SessionPair> {
    const familyId = newId();
    await this.redis.set(fKey(familyId), "1", "EX", this.refreshTtlS);
    return this.issuePair({ userId, accountId, familyId });
  }

  async getSession(sessionId: string): Promise<SessionData | null> {
    const raw = await this.redis.get(sKey(sessionId));
    if (!raw) return null;
    const data = JSON.parse(raw) as SessionData;
    // Family revoked (e.g. refresh-token reuse) kills live sessions too.
    if (!(await this.redis.get(fKey(data.familyId)))) {
      await this.redis.del(sKey(sessionId));
      return null;
    }
    return data;
  }

  /**
   * Rotates a refresh token. Returns the new pair, or null if the token is
   * unknown/expired/reused (in which case the family is revoked).
   */
  async rotate(refreshId: string): Promise<SessionPair | null> {
    const raw = await this.redis.getdel(rKey(refreshId));
    if (!raw) return null; // unknown, expired, or already consumed
    const data = JSON.parse(raw) as SessionData;
    if (!(await this.redis.get(fKey(data.familyId)))) return null;
    return this.issuePair(data);
  }

  /**
   * Marks a refresh id as consumed-and-reused: called when a token that fails
   * rotate() looks like a replay. Revokes nothing extra here because rotate()
   * already GETDELs; family revocation happens in revokeFamilyOf.
   */
  async revokeFamilyOf(data: SessionData): Promise<void> {
    await this.redis.del(fKey(data.familyId));
  }

  /** Logout: drop this session + refresh + the whole family. */
  async destroy(pair: Partial<SessionPair>, familyId?: string): Promise<void> {
    const keys: string[] = [];
    if (pair.sessionId) keys.push(sKey(pair.sessionId));
    if (pair.refreshId) keys.push(rKey(pair.refreshId));
    if (familyId) keys.push(fKey(familyId));
    if (keys.length) await this.redis.del(...keys);
  }

  private async issuePair(data: SessionData): Promise<SessionPair> {
    const sessionId = newId();
    const refreshId = newId();
    const json = JSON.stringify(data);
    await this.redis
      .multi()
      .set(sKey(sessionId), json, "EX", this.sessionTtlS)
      .set(rKey(refreshId), json, "EX", this.refreshTtlS)
      .exec();
    return { sessionId, refreshId };
  }
}
