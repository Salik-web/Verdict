// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import { Pool } from "pg";
import * as schema from "./schema.js";

export type Database = NodePgDatabase<typeof schema>;

/**
 * Creates a pg Pool + Drizzle instance. Callers own the lifecycle and must
 * call pool.end() on shutdown. The long-lived app uses a single shared pool
 * (see getDb); scripts create their own and close it.
 */
export function createDb(databaseUrl: string): {
  db: Database;
  pool: Pool;
} {
  const pool = new Pool({ connectionString: databaseUrl });
  const db = drizzle(pool, { schema });
  return { db, pool };
}

let shared: { db: Database; pool: Pool } | undefined;

/** Process-wide shared pool for the running server. */
export function getDb(databaseUrl: string): Database {
  shared ??= createDb(databaseUrl);
  return shared.db;
}

export async function closeDb(): Promise<void> {
  if (shared) {
    await shared.pool.end();
    shared = undefined;
  }
}
