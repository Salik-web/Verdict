/**
 * Migration runner. Applies db/migrations/*.sql in filename order, each in its
 * own transaction, recording applied versions in schema_migrations. Idempotent:
 * already-applied files are skipped. The SQL files are the source of truth.
 *
 *   pnpm --filter @geo/api db:migrate
 */
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { Pool } from "pg";
import { loadDotEnv, migrationsDir, requireDatabaseUrl } from "./paths.js";

async function main(): Promise<void> {
  loadDotEnv();
  const pool = new Pool({ connectionString: requireDatabaseUrl() });

  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version     text PRIMARY KEY,
        applied_at  timestamptz NOT NULL DEFAULT now()
      );
    `);

    const files = readdirSync(migrationsDir)
      .filter((f) => f.endsWith(".sql"))
      .sort();

    const applied = new Set(
      (
        await pool.query<{ version: string }>(
          "SELECT version FROM schema_migrations",
        )
      ).rows.map((r) => r.version),
    );

    let ran = 0;
    for (const file of files) {
      if (applied.has(file)) {
        console.log(`= skip ${file} (already applied)`);
        continue;
      }
      const sql = readFileSync(path.join(migrationsDir, file), "utf8");
      const client = await pool.connect();
      try {
        await client.query("BEGIN");
        await client.query(sql);
        await client.query(
          "INSERT INTO schema_migrations (version) VALUES ($1)",
          [file],
        );
        await client.query("COMMIT");
        console.log(`+ applied ${file}`);
        ran += 1;
      } catch (err) {
        await client.query("ROLLBACK");
        throw new Error(`Migration ${file} failed: ${(err as Error).message}`);
      } finally {
        client.release();
      }
    }
    console.log(ran === 0 ? "Up to date." : `Applied ${ran} migration(s).`);
  } finally {
    await pool.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
