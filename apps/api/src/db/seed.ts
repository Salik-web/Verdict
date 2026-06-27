/**
 * Seed runner. Applies db/seed.sql (idempotent) to load the demo account.
 *
 *   pnpm --filter @geo/api db:seed
 */
import { readFileSync } from "node:fs";
import { Pool } from "pg";
import { loadDotEnv, requireDatabaseUrl, seedFile } from "./paths.js";

async function main(): Promise<void> {
  loadDotEnv();
  const pool = new Pool({ connectionString: requireDatabaseUrl() });
  try {
    await pool.query(readFileSync(seedFile, "utf8"));
    console.log("Seed applied.");
  } finally {
    await pool.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
