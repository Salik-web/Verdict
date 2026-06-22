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
