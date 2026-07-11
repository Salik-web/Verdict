import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { AccountRepository } from "../repositories/account-repository.js";
import { parse } from "../validate.js";

const updateSchema = z.object({
  name: z.string().min(2).max(120).optional(),
  domain: z.string().max(255).nullable().optional(),
  brandName: z.string().max(120).nullable().optional(),
  brandAliases: z.array(z.string().max(120)).max(20).optional(),
  settings: z.record(z.unknown()).optional(),
});

/**
 * The account is always the CALLER'S account (from the session) — there is no
 * /accounts/:id, so cross-tenant reads are structurally impossible here.
 */
export function registerAccountRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const repo = new AccountRepository(ctx.db);

  app.get("/account", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId } = authOf(req);
    const account = await repo.findById(accountId);
    if (!account) return reply.code(404).send({ error: "not_found" });
    // Billing identifiers stay server-side.
    const { stripeCustomerId: _c, stripeSubscriptionId: _s, ...safe } = account;
    return safe;
  });

  app.patch("/account", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId } = authOf(req);
    const patch = parse(updateSchema, req.body);
    const updated = await repo.update(accountId, patch);
    if (!updated) return reply.code(404).send({ error: "not_found" });
    const { stripeCustomerId: _c, stripeSubscriptionId: _s, ...safe } = updated;
    return safe;
  });
}
