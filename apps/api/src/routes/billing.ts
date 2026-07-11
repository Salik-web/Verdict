import type { FastifyInstance } from "fastify";
import { authOf, buildRequireAuth } from "../auth/plugin.js";
import type { AppContext } from "../context.js";
import { limitsFor } from "../plans.js";
import { AccountRepository } from "../repositories/account-repository.js";

/**
 * Billing STUB — plan/subscription fields live on accounts; real Stripe
 * integration lands with the frontend. The hooks below are the contract:
 *
 * - POST /billing/checkout   -> will create a Stripe Checkout session
 *                               (server-side; we NEVER touch raw card data).
 * - POST /billing/webhook    -> will verify the Stripe-Signature header
 *                               (constructEvent w/ webhook secret) BEFORE
 *                               trusting any payload, then update the
 *                               account's plan/subscription fields.
 */
export function registerBillingRoutes(
  app: FastifyInstance,
  ctx: AppContext,
): void {
  const requireAuth = buildRequireAuth(ctx.sessions);
  const accounts = new AccountRepository(ctx.db);

  // Current plan + limits + subscription status (safe fields only).
  app.get("/billing", { preHandler: requireAuth }, async (req, reply) => {
    const { accountId } = authOf(req);
    const account = await accounts.findById(accountId);
    if (!account) return reply.code(404).send({ error: "not_found" });
    return {
      plan: account.plan,
      subscriptionStatus: account.subscriptionStatus,
      trialEndsAt: account.trialEndsAt,
      currentPeriodEnd: account.currentPeriodEnd,
      limits: limitsFor(account.plan),
    };
  });

  app.post(
    "/billing/checkout",
    { preHandler: requireAuth },
    async (_req, reply) => {
      return reply.code(501).send({
        error: "not_implemented",
        detail: "Stripe checkout lands with the frontend phase.",
      });
    },
  );

  // Webhook is unauthenticated by design (Stripe calls it) but MUST verify
  // the signature once implemented. Until then it accepts nothing.
  app.post("/billing/webhook", async (_req, reply) => {
    return reply.code(501).send({ error: "not_implemented" });
  });
}
