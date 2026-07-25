import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { readArtifact } from "../artifacts.js";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { DashboardRepository } from "../repositories/dashboard-repository.js";
import { parse, uuidParam } from "../validate.js";

const scanFilter = z.object({
  scan_id: z.string().uuid().optional(),
  limit: z.coerce.number().int().min(1).max(500).default(100),
});

const gapFilter = z.object({
  status: z
    .enum(["open", "planned", "in_progress", "resolved", "dismissed"])
    .optional(),
  limit: z.coerce.number().int().min(1).max(500).default(100),
});

const assetFilter = z.object({
  status: z
    .enum(["draft", "generated", "validated", "published", "rejected"])
    .optional(),
  limit: z.coerce.number().int().min(1).max(500).default(100),
});

const verificationFilter = z.object({
  asset_id: z.string().uuid().optional(),
  limit: z.coerce.number().int().min(1).max(500).default(100),
});

/** Read-only dashboard data; the pipeline writes these tables. */
export function registerDashboardRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const repo = new DashboardRepository(ctx.db);

  app.get("/mentions", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    const q = parse(scanFilter, req.query);
    const rows = await repo.listMentions(accountId, {
      scanId: q.scan_id,
      limit: q.limit,
    });
    // bigint ids serialize as strings.
    return rows.map((r) => ({ ...r, id: r.id.toString() }));
  });

  app.get("/gaps", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    const q = parse(gapFilter, req.query);
    return repo.listGaps(accountId, { status: q.status, limit: q.limit });
  });

  app.get("/assets", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    const q = parse(assetFilter, req.query);
    return repo.listAssets(accountId, { status: q.status, limit: q.limit });
  });

  // Single asset + its generated content, read from disk (content_ref). The HTML
  // is already nh3-sanitized; the browser renders it in a sandboxed iframe. We
  // return JSON (no HTML served from this origin), so the global CSP is untouched.
  app.get("/assets/:id", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId } = authOf(req);
    const { id } = parse(uuidParam, req.params);
    const row = await repo.getAsset(accountId, id);
    if (!row) return reply.code(404).send({ error: "not_found" });

    let content: string | null = null;
    let contentError: string | null = null;
    if (row.contentRef) {
      try {
        content = await readArtifact(ctx.config, accountId, id, row.contentRef);
      } catch (err) {
        // Missing/oddly-shaped ref shouldn't 500 the row — surface it instead.
        contentError = (err as Error).message ?? String(err);
      }
    }
    return { ...row, content, contentError };
  });

  app.get("/verifications", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    const q = parse(verificationFilter, req.query);
    return repo.listVerifications(accountId, {
      assetId: q.asset_id,
      limit: q.limit,
    });
  });

  app.get(
    "/verifications/:id",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId } = authOf(req);
      const { id } = parse(uuidParam, req.params);
      const row = await repo.getVerification(accountId, id);
      return row ?? reply.code(404).send({ error: "not_found" });
    },
  );

  app.get("/share-of-voice", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    const q = parse(scanFilter, req.query);
    return repo.listShareOfVoice(accountId, {
      scanId: q.scan_id,
      limit: q.limit,
    });
  });
}
