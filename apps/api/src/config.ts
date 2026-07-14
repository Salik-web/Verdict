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
  return parsed.data;
}
