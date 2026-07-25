import type { FastifyInstance, FastifyReply } from "fastify";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { PipelineClientError } from "../internal/pipeline-client.js";
import { checkScanQuota } from "../quota.js";
import { AuditRepository } from "../repositories/audit-repository.js";
import { DashboardRepository } from "../repositories/dashboard-repository.js";
import { ScanRepository } from "../repositories/scan-repository.js";
import { parse, uuidParam } from "../validate.js";

/**
 * Manual, per-stage pipeline triggers — re-run ONE stage without a whole scan.
 *
 * `POST /scans` runs the full chain; these exist for iterating on a single stage.
 * Same rules as everywhere else: the resource is looked up as (accountId, id) so
 * another tenant's id simply 404s, and each trigger is quota-checked (a re-run
 * costs model calls, so it can't be used to walk around the cap).
 */
export function registerStageRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const scans = new ScanRepository(ctx.db);
  const dashboard = new DashboardRepository(ctx.db);
  const audit = new AuditRepository(ctx.db);

  /** Shared: tenant-scoped lookup + quota, then hand off to the pipeline. */
  async function trigger(
    reply: FastifyReply,
    opts: {
      accountId: string;
      userId: string;
      ip: string;
      exists: boolean;
      action: string;
      resourceType: string;
      resourceId: string;
      call: () => Promise<unknown>;
    },
  ) {
    if (!opts.exists) return reply.code(404).send({ error: "not_found" });

    const quota = await checkScanQuota(ctx, opts.accountId);
    if (!quota.ok) {
      return reply
        .code(429)
        .header("Retry-After", String(quota.retryAfter))
        .send({ error: "quota_exceeded", limit: quota.limit, used: quota.used });
    }

    try {
      const result = await opts.call();
      void audit.record({
        accountId: opts.accountId,
        actorType: "user",
        actorId: opts.userId,
        action: opts.action,
        resourceType: opts.resourceType,
        resourceId: opts.resourceId,
        ip: opts.ip,
      });
      return reply.code(202).send(result);
    } catch (err) {
      const status = err instanceof PipelineClientError ? 502 : 500;
      return reply
        .code(status)
        .send({ error: "pipeline_unreachable", resourceId: opts.resourceId });
    }
  }

  app.post(
    "/scans/:id/diagnose",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId, userId } = authOf(req);
      const { id } = parse(uuidParam, req.params);
      const scan = await scans.findById(accountId, id);
      return trigger(reply, {
        accountId,
        userId,
        ip: req.ip,
        exists: Boolean(scan),
        action: "stage.diagnose",
        resourceType: "scan",
        resourceId: id,
        call: () => ctx.pipeline.triggerDiagnosis({ scanId: id, accountId }),
      });
    },
  );

  app.post(
    "/scans/:id/execute",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId, userId } = authOf(req);
      const { id } = parse(uuidParam, req.params);
      const scan = await scans.findById(accountId, id);
      return trigger(reply, {
        accountId,
        userId,
        ip: req.ip,
        exists: Boolean(scan),
        action: "stage.execute",
        resourceType: "scan",
        resourceId: id,
        call: () => ctx.pipeline.triggerExecution({ scanId: id, accountId }),
      });
    },
  );

  // Forces the verification re-measure now, instead of waiting for the
  // pipeline's scheduled delay to make this asset due.
  app.post(
    "/assets/:id/verify",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId, userId } = authOf(req);
      const { id } = parse(uuidParam, req.params);
      const asset = await dashboard.getAsset(accountId, id);
      return trigger(reply, {
        accountId,
        userId,
        ip: req.ip,
        exists: Boolean(asset),
        action: "stage.verify",
        resourceType: "asset",
        resourceId: id,
        call: () => ctx.pipeline.triggerVerification({ assetId: id, accountId }),
      });
    },
  );
}
