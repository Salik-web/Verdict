import type { FastifyInstance, FastifyReply } from "fastify";
import { z } from "zod";
import {
  REFRESH_COOKIE,
  SESSION_COOKIE,
  authOf,
  buildRequireAuth,
  cookieBaseOptions,
} from "../auth/plugin.js";
import { AuthError } from "../auth/service.js";
import type { AppContext } from "../context.js";
import { AuditRepository } from "../repositories/audit-repository.js";
import { UserRepository } from "../repositories/user-repository.js";
import { parse } from "../validate.js";

const signupSchema = z.object({
  email: z.string().email().max(254),
  password: z.string().min(10).max(200),
  name: z.string().min(1).max(120).optional(),
  accountName: z.string().min(2).max(120),
});

const loginSchema = z.object({
  email: z.string().email().max(254),
  password: z.string().min(1).max(200),
});

export function registerAuthRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const audit = new AuditRepository(ctx.db);

  const setAuthCookies = (
    reply: FastifyReply,
    pair: { sessionId: string; refreshId: string },
  ) => {
    reply.setCookie(SESSION_COOKIE, pair.sessionId, {
      ...cookieBaseOptions,
      maxAge: ctx.config.SESSION_TTL_S,
    });
    reply.setCookie(REFRESH_COOKIE, pair.refreshId, {
      ...cookieBaseOptions,
      path: "/auth/refresh",
      maxAge: ctx.config.REFRESH_TTL_S,
    });
  };

  // Strict per-IP limits on auth endpoints (credential stuffing/brute force).
  const strict = (max: number) => ({
    config: { rateLimit: { max, timeWindow: "1 minute" } },
  });

  app.post("/auth/signup", strict(5), async (req, reply) => {
    const body = parse(signupSchema, req.body);
    try {
      const result = await ctx.auth.signup(body);
      setAuthCookies(reply, result.pair);
      void audit.record({
        accountId: result.accountId,
        actorType: "user",
        actorId: result.userId,
        action: "auth.signup",
        ip: req.ip,
      });
      return reply
        .code(201)
        .send({ userId: result.userId, accountId: result.accountId });
    } catch (err) {
      if (err instanceof AuthError && err.code === "email_taken") {
        // Same shape as success-adjacent errors; avoids user enumeration detail.
        return reply.code(409).send({ error: "email_taken" });
      }
      throw err;
    }
  });

  app.post("/auth/login", strict(5), async (req, reply) => {
    const body = parse(loginSchema, req.body);
    const result = await ctx.auth.login(body.email, body.password);
    if (!result) {
      return reply.code(401).send({ error: "invalid_credentials" });
    }
    setAuthCookies(reply, result.pair);
    void audit.record({
      accountId: result.accountId,
      actorType: "user",
      actorId: result.userId,
      action: "auth.login",
      ip: req.ip,
    });
    return { userId: result.userId, accountId: result.accountId };
  });

  app.post("/auth/refresh", strict(10), async (req, reply) => {
    const raw = req.cookies[REFRESH_COOKIE];
    const unsigned = raw ? req.unsignCookie(raw) : { valid: false as const };
    if (!unsigned.valid || !unsigned.value) {
      return reply.code(401).send({ error: "unauthorized" });
    }
    const pair = await ctx.auth.refresh(unsigned.value);
    if (!pair) {
      // Unknown/reused token — clear cookies; family revocation already applied.
      reply.clearCookie(SESSION_COOKIE, { path: "/" });
      reply.clearCookie(REFRESH_COOKIE, { path: "/auth/refresh" });
      return reply.code(401).send({ error: "unauthorized" });
    }
    setAuthCookies(reply, pair);
    return { ok: true };
  });

  app.post("/auth/logout", async (req, reply) => {
    const sessionRaw = req.cookies[SESSION_COOKIE];
    const refreshRaw = req.cookies[REFRESH_COOKIE];
    const sessionId = sessionRaw
      ? req.unsignCookie(sessionRaw).value
      : undefined;
    const refreshId = refreshRaw
      ? req.unsignCookie(refreshRaw).value
      : undefined;
    await ctx.auth.logout(sessionId ?? undefined, refreshId ?? undefined);
    reply.clearCookie(SESSION_COOKIE, { path: "/" });
    reply.clearCookie(REFRESH_COOKIE, { path: "/auth/refresh" });
    return { ok: true };
  });

  app.get("/auth/me", { preHandler: requireAuth }, async (req) => {
    const { userId, accountId } = authOf(req);
    const user = await new UserRepository(ctx.db).findById(userId);
    return {
      userId,
      accountId,
      email: user?.email,
      name: user?.name,
      role: user?.role,
    };
  });
}
