// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import { z } from "zod";

/**
 * Environment contract for the API service. Validated once at boot — if a
 * required var is missing or malformed the process exits instead of starting
 * in a half-configured state. Never log the parsed result (it holds secrets).
 */
const envSchema = z.object({
  NODE_ENV: z
    .enum(["development", "test", "production"])
    .default("development"),
  HOST: z.string().default("0.0.0.0"),
  PORT: z.coerce.number().int().positive().default(3000),
  LOG_LEVEL: z
    .enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"])
    .default("info"),

  // Shared Postgres — the contract spine between services.
  DATABASE_URL: z.string().url(),
  // Redis for BullMQ (TS-side jobs).
  REDIS_URL: z.string().url(),

  // Internal service-to-service auth.
  INTERNAL_SHARED_SECRET: z.string().min(8),
  // Base URL of the Python pipeline's FastAPI service.
  PIPELINE_URL: z.string().url().default("http://localhost:8000"),
  // Filesystem root the pipeline writes generated asset artifacts under (its
  // content_ref values are relative to this). Local dev shares the disk; in prod
  // this becomes a shared/object store. Relative to the API process cwd.
  PIPELINE_ARTIFACTS_DIR: z.string().default("../../services/pipeline"),

  // Frontend origin for CORS (locked; not '*').
  FRONTEND_ORIGIN: z.string().url().default("http://localhost:5173"),
  // Signs session cookies. Rotate to invalidate all cookies.
  COOKIE_SECRET: z.string().min(16),
  // 32-byte hex master key (KEK) for envelope encryption of CMS credentials.
  // Generate: openssl rand -hex 32
  MASTER_ENCRYPTION_KEY: z
    .string()
    .regex(/^[0-9a-fA-F]{64}$/, "must be 32 bytes hex (64 hex chars)"),
  // Session lifetimes (seconds).
  SESSION_TTL_S: z.coerce.number().int().positive().default(900), // 15 min
  REFRESH_TTL_S: z.coerce.number().int().positive().default(1209600), // 14 days

  // Error tracking. Optional — blank leaves Sentry off (dev/test boot with no
  // secret); set it in prod to turn on scrubbed error reporting.
  SENTRY_DSN: z.string().url().optional(),
});

export type AppConfig = z.infer<typeof envSchema>;

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const parsed = envSchema.safeParse(env);
  if (!parsed.success) {
    // Surface field names only — never the values — to avoid leaking secrets.
    const issues = parsed.error.issues
      .map((i) => `  - ${i.path.join(".") || "(root)"}: ${i.message}`)
      .join("\n");
    throw new Error(`Invalid environment configuration:\n${issues}`);
  }
  assertNoPlaceholderSecrets(parsed.data);
  return parsed.data;
}

/**
 * Placeholder secrets that ship as working defaults so `docker compose up`
 * needs no setup. They are safe on localhost and catastrophic anywhere else:
 * INTERNAL_SHARED_SECRET is the only thing guarding the pipeline's internal
 * trigger endpoints, COOKIE_SECRET forges any session, and an all-zero
 * MASTER_ENCRYPTION_KEY leaves stored CMS credentials effectively plaintext.
 *
 * Matching is on the obvious shapes rather than exact strings, so a user who
 * edited the file at all is not blocked, while a user who never touched it
 * cannot reach production by accident.
 */
const PLACEHOLDERS: Record<string, (v: string) => boolean> = {
  INTERNAL_SHARED_SECRET: (v) => v.includes("change-me"),
  COOKIE_SECRET: (v) => v.includes("change-me"),
  MASTER_ENCRYPTION_KEY: (v) => /^0+$/.test(v),
};

const HOW_TO_GENERATE: Record<string, string> = {
  INTERNAL_SHARED_SECRET: "openssl rand -hex 32",
  COOKIE_SECRET: "openssl rand -hex 32",
  MASTER_ENCRYPTION_KEY:
    "openssl rand -hex 32   (must be exactly 32 bytes hex / 64 chars)",
};

export function assertNoPlaceholderSecrets(config: AppConfig): void {
  // Localhost stays frictionless: that is the entire point of the defaults.
  if (config.NODE_ENV !== "production") return;

  const offenders = Object.entries(PLACEHOLDERS)
    .filter(([key, isPlaceholder]) =>
      isPlaceholder(String(config[key as keyof AppConfig] ?? "")),
    )
    .map(([key]) => key);

  if (offenders.length === 0) return;

  const lines = offenders
    .map(
      (key) =>
        "  - " +
        key +
        " is still the development placeholder.\n" +
        "    Generate a real value with:  " +
        HOW_TO_GENERATE[key],
    )
    .join("\n");

  throw new Error(
    "Refusing to start with NODE_ENV=production and placeholder secrets:\n" +
      lines +
      "\n\nThese defaults exist so `docker compose up` works with no setup. " +
      "They are public knowledge - this repository ships them - so they " +
      "protect nothing outside localhost. Set real values, or run with " +
      "NODE_ENV=development if this is a local machine.",
  );
}
