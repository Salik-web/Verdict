import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { DashboardRepository } from "../repositories/dashboard-repository.js";
import { parse } from "../validate.js";

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

  app.get("/share-of-voice", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    const q = parse(scanFilter, req.query);
    return repo.listShareOfVoice(accountId, {
      scanId: q.scan_id,
      limit: q.limit,
    });
  });
}
