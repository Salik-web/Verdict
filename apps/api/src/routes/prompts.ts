// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { limitsFor } from "../plans.js";
import { PipelineClientError } from "../internal/pipeline-client.js";
import { AccountRepository } from "../repositories/account-repository.js";
import { PromptRepository } from "../repositories/prompt-repository.js";
import { parse, uuidParam } from "../validate.js";

const createSchema = z.object({
  text: z.string().min(5).max(2000),
  category: z.string().max(80).optional(),
  promptGroup: z.string().max(80).optional(),
  active: z.boolean().default(true),
});

const updateSchema = createSchema.partial();

const listQuery = z.object({
  active: z.coerce.boolean().optional(),
});

const generateSchema = z.object({
  // Upper bound only; the route clamps this to the plan's remaining headroom.
  count: z.coerce.number().int().min(1).max(50).optional(),
  category: z.string().min(2).max(120).optional(),
});

export function registerPromptRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const repo = new PromptRepository(ctx.db);
  const accounts = new AccountRepository(ctx.db);

  app.get("/prompts", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    const q = parse(listQuery, req.query);
    return repo.listByAccount(accountId, { activeOnly: q.active === true });
  });

  app.post("/prompts", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId } = authOf(req);
    const body = parse(createSchema, req.body);

    const account = await accounts.findById(accountId);
    const existing = await repo.listByAccount(accountId);
    if (existing.length >= limitsFor(account?.plan ?? "free").max_prompts) {
      return reply
        .code(429)
        .send({ error: "plan_limit_reached", resource: "prompts" });
    }
    return reply.code(201).send(await repo.create({ ...body, accountId }));
  });

  // POST /prompts/generate — the onboarding path. A fresh account has zero
  // prompts, and a scan with no prompts measures nothing, so the alternative is
  // asking a new user to invent 20-odd buyer-intent queries by hand.
  app.post(
    "/prompts/generate",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId } = authOf(req);
      const body = parse(generateSchema, req.body);

      const account = await accounts.findById(accountId);
      const limit = limitsFor(account?.plan ?? "free").max_prompts;
      const existing = await repo.listByAccount(accountId);
      const headroom = limit - existing.length;
      if (headroom <= 0) {
        return reply
          .code(429)
          .send({ error: "plan_limit_reached", resource: "prompts" });
      }

      try {
        // Never let generation push the account over its plan limit: ask for at
        // most the headroom the account actually has.
        const result = await ctx.pipeline.generatePrompts({
          accountId,
          count: Math.min(body.count ?? headroom, headroom),
          category: body.category,
        });
        return reply.code(201).send(result);
      } catch (err) {
        req.log.error({ err, accountId }, "prompt generation failed");
        const status =
          err instanceof PipelineClientError ? (err.status ?? 502) : 500;
        // 503 upstream means a provider key is missing — an operator problem the
        // user can be told about plainly, not an opaque 500.
        return reply.code(status === 503 ? 503 : 502).send({
          error:
            status === 503 ? "generation_unavailable" : "pipeline_unreachable",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    },
  );

  app.get("/prompts/:id", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId } = authOf(req);
    const { id } = parse(uuidParam, req.params);
    const row = await repo.findById(accountId, id);
    return row ?? reply.code(404).send({ error: "not_found" });
  });

  app.patch("/prompts/:id", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId } = authOf(req);
    const { id } = parse(uuidParam, req.params);
    const patch = parse(updateSchema, req.body);
    const row = await repo.update(accountId, id, patch);
    return row ?? reply.code(404).send({ error: "not_found" });
  });

  app.delete(
    "/prompts/:id",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId } = authOf(req);
      const { id } = parse(uuidParam, req.params);
      const deleted = await repo.delete(accountId, id);
      if (!deleted) return reply.code(404).send({ error: "not_found" });
      return reply.code(204).send();
    },
  );
}
