import fastifyCookie from "@fastify/cookie";
import fastifyCors from "@fastify/cors";
import fastifyHelmet from "@fastify/helmet";
import fastifyRateLimit from "@fastify/rate-limit";
import Fastify, { type FastifyInstance } from "fastify";
import { Redis } from "ioredis";
import type { HealthResponse } from "@geo/shared";
import { createRequire } from "node:module";
import { LocalAuthService } from "./auth/service.js";
import { SessionStore } from "./auth/session-store.js";
import type { AppConfig } from "./config.js";
import type { AppContext } from "./context.js";
import { Envelope } from "./crypto/envelope.js";
import { createDb } from "./db/client.js";
import { captureException } from "./observability.js";
import { PipelineClient } from "./internal/pipeline-client.js";
import { registerAccountRoutes } from "./routes/accounts.js";
import { registerAuthRoutes } from "./routes/auth.js";
import { registerBillingRoutes } from "./routes/billing.js";
import { registerCmsCredentialRoutes } from "./routes/cms-credentials.js";
import { registerCompetitorRoutes } from "./routes/competitors.js";
import { registerDashboardRoutes } from "./routes/dashboard.js";
import { registerPromptRoutes } from "./routes/prompts.js";
import { registerScanRoutes } from "./routes/scans.js";
import { registerStageRoutes } from "./routes/stages.js";
import { registerVerifiedFactRoutes } from "./routes/verified-facts.js";
import { ValidationFailed, sendValidationError } from "./validate.js";

const require = createRequire(import.meta.url);
const { version: SERVICE_VERSION } = require("../package.json") as {
  version: string;
};

export async function buildServer(config: AppConfig): Promise<{
  app: FastifyInstance;
  ctx: AppContext;
}> {
  const app = Fastify({
    logger: { level: config.LOG_LEVEL },
    trustProxy: true,
  });

  // ── Context ──────────────────────────────────────────────────────────
  const { db, pool } = createDb(config.DATABASE_URL);
  const redis = new Redis(config.REDIS_URL, { maxRetriesPerRequest: 2 });
  const sessions = new SessionStore(
    redis,
    config.SESSION_TTL_S,
    config.REFRESH_TTL_S,
  );
  const ctx: AppContext = {
    config,
    db,
    redis,
    sessions,
    auth: new LocalAuthService(db, sessions),
    envelope: new Envelope(config.MASTER_ENCRYPTION_KEY),
    pipeline: new PipelineClient({
      baseUrl: config.PIPELINE_URL,
      secret: config.INTERNAL_SHARED_SECRET,
    }),
  };

  app.addHook("onClose", async () => {
    await pool.end();
    redis.disconnect();
  });

  // ── Security baseline ────────────────────────────────────────────────
  await app.register(fastifyHelmet, {
    // API serves JSON only; a restrictive CSP is still cheap defense in depth.
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'none'"],
        frameAncestors: ["'none'"],
      },
    },
    strictTransportSecurity: {
      maxAge: 15552000, // 180 days
      includeSubDomains: true,
    },
    frameguard: { action: "deny" },
  });
  await app.register(fastifyCors, {
    origin: config.FRONTEND_ORIGIN, // locked to the frontend, never '*'
    credentials: true,
  });
  await app.register(fastifyCookie, { secret: config.COOKIE_SECRET });
  await app.register(fastifyRateLimit, {
    global: true,
    max: 100, // default per-IP ceiling; auth routes override stricter
    timeWindow: "1 minute",
    redis, // shared across instances
    nameSpace: "rl:",
    addHeadersOnExceeding: { "x-ratelimit-remaining": true },
    errorResponseBuilder: (_req, context) => ({
      statusCode: 429,
      error: "rate_limited",
      message: `Rate limit exceeded, retry in ${context.after}`,
    }),
  });

  // Zod failures -> 400 with field details; everything else -> generic 500.
  app.setErrorHandler(async (err: unknown, _req, reply) => {
    if (err instanceof ValidationFailed) {
      return sendValidationError(reply, err);
    }
    captureException(err); // no-op unless Sentry is active
    app.log.error({ err }, "unhandled error");
    if (!reply.sent) {
      const maybe = err as { statusCode?: unknown; message?: unknown };
      const status =
        typeof maybe.statusCode === "number" ? maybe.statusCode : 500;
      await reply.code(status).send({
        error:
          status === 500 ? "internal_error" : String(maybe.message ?? "error"),
      });
    }
  });

  // ── Routes ───────────────────────────────────────────────────────────
  app.get(
    "/health",
    { config: { rateLimit: false } },
    async (): Promise<HealthResponse> => ({
      status: "ok",
      service: "api",
      version: SERVICE_VERSION,
      time: new Date().toISOString(),
    }),
  );

  app.get("/internal/pipeline-health", async (_req, reply) => {
    try {
      const pong = await ctx.pipeline.ping();
      return { status: "ok", pipeline: pong } as const;
    } catch (err) {
      app.log.error({ err }, "pipeline ping failed");
      return reply
        .code(502)
        .send({ status: "error", message: "pipeline unreachable" });
    }
  });

  registerAuthRoutes(app, ctx);
  registerAccountRoutes(app, ctx);
  registerCompetitorRoutes(app, ctx);
  registerPromptRoutes(app, ctx);
  registerVerifiedFactRoutes(app, ctx);
  registerScanRoutes(app, ctx);
  registerStageRoutes(app, ctx);
  registerDashboardRoutes(app, ctx);
  registerCmsCredentialRoutes(app, ctx);
  registerBillingRoutes(app, ctx);

  return { app, ctx };
}
