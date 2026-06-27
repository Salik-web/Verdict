/**
 * Proves the TS service can read the seeded demo account through its repository
 * layer (no raw SQL). Exits non-zero on any assertion failure.
 *
 *   pnpm --filter @geo/api db:check
 */
import { createDb } from "./client.js";
import { loadDotEnv, requireDatabaseUrl } from "./paths.js";
import { AccountRepository } from "../repositories/account-repository.js";
import { CompetitorRepository } from "../repositories/competitor-repository.js";
import { PromptRepository } from "../repositories/prompt-repository.js";

const DEMO_ACCOUNT_ID = "00000000-0000-0000-0000-000000000001";

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(`CHECK FAILED: ${msg}`);
}

async function main(): Promise<void> {
  loadDotEnv();
  const { db, pool } = createDb(requireDatabaseUrl());
  try {
    const accounts = new AccountRepository(db);
    const competitors = new CompetitorRepository(db);
    const prompts = new PromptRepository(db);

    const account = await accounts.findById(DEMO_ACCOUNT_ID);
    assert(account, "demo account not found — did you run db:seed?");
    assert(account.slug === "acme-analytics", "unexpected demo account slug");

    const comps = await competitors.listByAccount(DEMO_ACCOUNT_ID);
    assert(comps.length >= 3, `expected >=3 competitors, got ${comps.length}`);

    const activePrompts = await prompts.listByAccount(DEMO_ACCOUNT_ID, {
      activeOnly: true,
    });
    assert(
      activePrompts.length >= 3,
      `expected >=3 active prompts, got ${activePrompts.length}`,
    );

    console.log("OK — TS repositories read the demo account:");
    console.log(`  account:     ${account.name} (${account.slug})`);
    console.log(`  competitors: ${comps.map((c) => c.name).join(", ")}`);
    console.log(`  prompts:     ${activePrompts.length} active`);
  } finally {
    await pool.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
