// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { VerifiedFactRepository } from "../repositories/verified-fact-repository.js";
import { parse, uuidParam } from "../validate.js";

const createSchema = z.object({
  factType: z.string().min(1).max(80),
  key: z.string().min(1).max(200),
  value: z.unknown().refine((v) => v !== undefined, "value is required"),
  source: z.string().max(500).optional(),
  confidence: z.number().min(0).max(1).optional(),
  isActive: z.boolean().default(true),
});

const updateSchema = z.object({
  value: z.unknown().optional(),
  source: z.string().max(500).nullable().optional(),
  confidence: z.number().min(0).max(1).nullable().optional(),
  isActive: z.boolean().optional(),
});

export function registerVerifiedFactRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const repo = new VerifiedFactRepository(ctx.db);

  app.get("/verified-facts", { preHandler: requireAuth }, async (req) => {
    const { accountId } = authOf(req);
    return repo.listByAccount(accountId);
  });

  app.post(
    "/verified-facts",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId } = authOf(req);
      const body = parse(createSchema, req.body);
      const row = await repo.create({
        accountId,
        factType: body.factType,
        key: body.key,
        value: body.value,
        source: body.source,
        confidence: body.confidence?.toString(),
        isActive: body.isActive,
      });
      return reply.code(201).send(row);
    },
  );

  app.patch(
    "/verified-facts/:id",
    { preHandler: requireAuth },
    async (req, reply) => {
      const { accountId } = authOf(req);
      const { id } = parse(uuidParam, req.params);
      const body = parse(updateSchema, req.body);
      const row = await repo.update(accountId, id, {
        ...(body.value !== undefined && { value: body.value }),
        ...(body.source !== undefined && { source: body.source }),
        ...(body.confidence !== undefined && {
          confidence: body.confidence?.toString() ?? null,
        }),
        ...(body.isActive !== undefined && { isActive: body.isActive }),
      });
      return row ?? reply.code(404).send({ error: "not_found" });
    },
  );

  app.delete(
    "/verified-facts/:id",
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
