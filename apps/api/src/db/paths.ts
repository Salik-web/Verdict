// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** Repo root, resolved from apps/api/src/db. */
export const repoRoot = path.resolve(here, "../../../..");
export const migrationsDir = path.join(repoRoot, "db", "migrations");
export const seedFile = path.join(repoRoot, "db", "seed.sql");

/**
 * Loads apps/api/.env in dev. No-op when absent (CI/prod use the real env).
 * Existing process.env values win.
 */
export function loadDotEnv(): void {
  try {
    process.loadEnvFile();
  } catch {
    /* no .env file — rely on the ambient environment */
  }
}

export function requireDatabaseUrl(): string {
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error("DATABASE_URL is not set (see apps/api/.env.example)");
  }
  return url;
}
