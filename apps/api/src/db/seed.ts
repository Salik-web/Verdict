// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Seed runner. Applies db/seed.sql (idempotent) to load the demo account, then
 * creates its owner user with a FRESHLY GENERATED password.
 *
 *   pnpm --filter @geo/api db:seed
 *
 * Two things this deliberately does not do:
 *
 * 1. **It does not run in production.** Seeding writes a known-id account, a
 *    login, and fake competitor data. Nothing good happens if that lands in a
 *    real environment, and the previous version would happily do it against
 *    whatever DATABASE_URL it was pointed at. Set `ALLOW_SEED=1` to override
 *    deliberately (restoring a staging box), never by accident.
 *
 * 2. **It does not ship a password.** db/seed.sql used to carry a fixed argon2
 *    hash with the plaintext in a comment above it — a credential every reader
 *    of a public repository knows. The password is generated here, printed
 *    once, and never written to a file. Pass DEMO_PASSWORD to choose your own
 *    (useful for a scripted local setup).
 */
import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { Pool } from "pg";
import { hashPassword } from "../auth/password.js";
import { loadDotEnv, requireDatabaseUrl, seedFile } from "./paths.js";

const DEMO_ACCOUNT_ID = "00000000-0000-0000-0000-000000000001";
const DEMO_USER_ID = "00000000-0000-0000-0000-0000000000a1";
const DEMO_EMAIL = "owner@acme.example.com";

/** Refuse to seed anything that looks like production unless told twice. */
function assertSeedable(): void {
  if (process.env.ALLOW_SEED === "1") return;

  const env = (process.env.NODE_ENV ?? "development").toLowerCase();
  if (env === "production" || env === "prod") {
    throw new Error(
      `Refusing to seed with NODE_ENV=${env}. The seed writes a demo account, ` +
        "a login, and fake competitor data. Set ALLOW_SEED=1 if you genuinely " +
        "mean to do this.",
    );
  }
}

/** A password with real entropy: 24 base64url chars ≈ 144 bits. */
function generatePassword(): string {
  return randomBytes(18).toString("base64url");
}

async function main(): Promise<void> {
  loadDotEnv();
  assertSeedable();

  const password = process.env.DEMO_PASSWORD || generatePassword();
  const generated = !process.env.DEMO_PASSWORD;
  const passwordHash = await hashPassword(password);

  const pool = new Pool({ connectionString: requireDatabaseUrl() });
  try {
    await pool.query(readFileSync(seedFile, "utf8"));
    // The owner user lives here rather than in the SQL so its hash is never a
    // committed constant. ON CONFLICT keeps the seed idempotent — re-running
    // rotates the demo password rather than failing.
    await pool.query(
      `INSERT INTO users (id, account_id, email, name, role, status, password_hash)
       VALUES ($1, $2, $3, 'Acme Owner', 'owner', 'active', $4)
       ON CONFLICT (id) DO UPDATE SET password_hash = EXCLUDED.password_hash`,
      [DEMO_USER_ID, DEMO_ACCOUNT_ID, DEMO_EMAIL, passwordHash],
    );

    console.log("Seed applied.");
    console.log(`  demo login: ${DEMO_EMAIL}`);
    if (generated) {
      console.log(`  password:   ${password}`);
      console.log(
        "  ^ generated just now and not stored anywhere. Re-run db:seed to " +
          "rotate it, or set DEMO_PASSWORD to choose your own.",
      );
    } else {
      console.log("  password:   (from DEMO_PASSWORD)");
    }
  } finally {
    await pool.end();
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
