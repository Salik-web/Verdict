import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { PipelineClientError } from "../internal/pipeline-client.js";
import { checkScanQuota } from "../quota.js";
import { AuditRepository } from "../repositories/audit-repository.js";
import { ScanRepository } from "../repositories/scan-repository.js";
import { parse, uuidParam } from "../validate.js";

const createSchema = z.object({
  // Which engines to measure; validated further (against config) by the pipeline.
  engines: z.array(z.string().min(1).max(40)).min(1).max(10).default(["all"]),
});

export function registerScanRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const scans = new ScanRepository(ctx.db);
  const audit = new AuditRepository(ctx.db);

  // POST /scans — creates the scan row, then asks the pipeline to run the FULL
  // loop for it: monitor -> diagnose -> plan+execute.
  app.post("/scans", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId, userId } = authOf(req);
    const body = parse(createSchema, req.body);

    // Usage quota keyed to the account's plan — this is also the cost cap.
    const quota = await checkScanQuota(ctx, accountId);
    if (!quota.ok) {
      return reply
        .code(429)
        .header("Retry-After", String(quota.retryAfter))
        .send({
          error: "quota_exceeded",
          limit: quota.limit,
          used: quota.used,
        });
    }

    const scan = await scans.create({
      accountId,
      status: "pending",
      engineSet: body.engines,
      triggeredBy: userId,
    });

    try {
      await ctx.pipeline.triggerScan({ scanId: scan.id, accountId });
    } catch (err) {
      // Scan row stays 'pending' with the error noted; a retry sweep can pick
      // it up later. Surface 502 so the caller knows the pipeline didn't start.
      req.log.error({ err, scanId: scan.id }, "pipeline trigger failed");
      const status = err instanceof PipelineClientError ? 502 : 500;
      return reply.code(status).send({
        error: "pipeline_unreachable",
        scanId: scan.id,
      });
    }

    void audit.record({
      accountId,
      actorType: "user",
      actorId: userId,
      action: "scan.trigger",
      resourceType: "scan",
      resourceId: scan.id,
      ip: req.ip,
    });
    return reply.code(202).send({ scanId: scan.id, status: scan.status });
  });

  app.get("/scans", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    return scans.listByAccount(accountId);
  });

  app.get("/scans/:id", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId } = authOf(req);
    const { id } = parse(uuidParam, req.params);
    const row = await scans.findById(accountId, id);
    return row ?? reply.code(404).send({ error: "not_found" });
  });
}
