import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { limitsFor } from "../plans.js";
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
