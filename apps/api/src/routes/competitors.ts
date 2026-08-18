// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { limitsFor } from "../plans.js";
import { AccountRepository } from "../repositories/account-repository.js";
import { CompetitorRepository } from "../repositories/competitor-repository.js";
import { domainSchema, parse, uuidParam } from "../validate.js";

const createSchema = z.object({
  name: z.string().min(1).max(120),
  domain: domainSchema.optional(),
  aliases: z.array(z.string().max(120)).max(20).default([]),
  isSelf: z.boolean().default(false),
});

const updateSchema = createSchema.partial();

export function registerCompetitorRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const repo = new CompetitorRepository(ctx.db);
  const accounts = new AccountRepository(ctx.db);

  app.get("/competitors", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    return repo.listByAccount(accountId);
  });

  app.post("/competitors", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId } = authOf(req);
    const body = parse(createSchema, req.body);

    const account = await accounts.findById(accountId);
    const existing = await repo.listByAccount(accountId);
    if (existing.length >= limitsFor(account?.plan ?? "free").max_competitors) {
      return reply
        .code(429)
        .send({ error: "plan_limit_reached", resource: "competitors" });
    }
    return reply.code(201).send(await repo.create({ ...body, accountId }));
  });

  app.get(
    "/competitors/:id",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId } = authOf(req);
      const { id } = parse(uuidParam, req.params);
      // Scoped lookup: another tenant's id simply doesn't exist here (404, not 403).
      const row = await repo.findById(accountId, id);
      return row ?? reply.code(404).send({ error: "not_found" });
    },
  );

  app.patch(
    "/competitors/:id",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId } = authOf(req);
      const { id } = parse(uuidParam, req.params);
      const patch = parse(updateSchema, req.body);
      const row = await repo.update(accountId, id, patch);
      return row ?? reply.code(404).send({ error: "not_found" });
    },
  );

  app.delete(
    "/competitors/:id",
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
