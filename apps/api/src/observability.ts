import * as Sentry from "@sentry/node";
import type { AppConfig } from "./config.js";

/**
 * Error tracking. Sentry is initialised **only when SENTRY_DSN is set**, so
 * dev/test boot with no secret and the SDK stays dormant. When it is set, PII is
 * never sent and a scrubber redacts known-sensitive keys before any event
 * leaves the process. Structured request logging is already handled by Fastify's
 * pino logger (server.ts) — this is purely exception capture.
 */

let started = false;

const SCRUB_KEYS = new Set([
  "x-internal-secret",
  "authorization",
  "cookie",
  "set-cookie",
  "internal_shared_secret",
  "database_url",
  "redis_url",
  "cookie_secret",
  "master_encryption_key",
  "sentry_dsn",
  "password",
  "token",
  "secret",
  "credentials",
  "ciphertext",
  "encrypteddek",
]);

function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [
        k,
        SCRUB_KEYS.has(k.toLowerCase()) ? "[redacted]" : redact(v),
      ]),
    );
  }
  return value;
}

/** Wire Sentry iff a DSN is configured. Returns true when actually started. */
export function initSentry(config: AppConfig): boolean {
  if (started) return true;
  if (!config.SENTRY_DSN) return false;

  Sentry.init({
    dsn: config.SENTRY_DSN,
    environment: config.NODE_ENV,
    sendDefaultPii: false,
    tracesSampleRate: 0,
    beforeSend: (event) => redact(event) as Sentry.ErrorEvent,
  });
  started = true;
  return true;
}

/** Report an exception if Sentry is active; a no-op otherwise. */
export function captureException(err: unknown): void {
  if (started) Sentry.captureException(err);
}
