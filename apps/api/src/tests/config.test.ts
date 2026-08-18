// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Production guard on placeholder secrets.
 *
 * This repository ships working placeholder secrets so `docker compose up`
 * needs no setup. That is a deliberate adoption trade, and it is only safe
 * because those values cannot reach production silently: the API refuses to
 * boot on them when NODE_ENV=production.
 *
 * Both halves matter and are tested here — the refusal, and the fact that the
 * localhost path is completely untouched.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { assertNoPlaceholderSecrets, type AppConfig } from "../config.js";

const PLACEHOLDER_KEK = "0".repeat(64);
const REAL_KEK = "a".repeat(64);

function config(over: Partial<AppConfig> = {}): AppConfig {
  return {
    NODE_ENV: "production",
    HOST: "0.0.0.0",
    PORT: 3000,
    LOG_LEVEL: "info",
    DATABASE_URL: "postgresql://geo:geo@localhost:5432/geo",
    REDIS_URL: "redis://localhost:6379/0",
    INTERNAL_SHARED_SECRET: "a-real-generated-secret-0123456789",
    PIPELINE_URL: "http://localhost:8000",
    PIPELINE_ARTIFACTS_DIR: "../../services/pipeline",
    FRONTEND_ORIGIN: "http://localhost:5173",
    COOKIE_SECRET: "a-real-generated-cookie-secret-0123456789",
    MASTER_ENCRYPTION_KEY: REAL_KEK,
    SESSION_TTL_S: 900,
    REFRESH_TTL_S: 1209600,
    ...over,
  } as AppConfig;
}

test("real secrets in production are accepted", () => {
  assert.doesNotThrow(() => assertNoPlaceholderSecrets(config()));
});

test("localhost is untouched — placeholders are fine outside production", () => {
  // The whole adoption story depends on this staying frictionless.
  for (const env of ["development", "test"] as const) {
    assert.doesNotThrow(() =>
      assertNoPlaceholderSecrets(
        config({
          NODE_ENV: env,
          INTERNAL_SHARED_SECRET: "dev-only-change-me-0123456789abcdef",
          COOKIE_SECRET: "dev-only-change-me-0123456789abcdef0123456789abcdef",
          MASTER_ENCRYPTION_KEY: PLACEHOLDER_KEK,
        }),
      ),
    );
  }
});

test("a placeholder INTERNAL_SHARED_SECRET refuses to boot in production", () => {
  assert.throws(
    () =>
      assertNoPlaceholderSecrets(
        config({ INTERNAL_SHARED_SECRET: "dev-only-change-me-0123456789abcdef" }),
      ),
    (err: Error) => {
      // Must name the variable AND how to fix it — an operator hitting this at
      // 2am should not have to read the source.
      assert.match(err.message, /INTERNAL_SHARED_SECRET/);
      assert.match(err.message, /openssl rand -hex 32/);
      return true;
    },
  );
});

test("a placeholder COOKIE_SECRET refuses to boot in production", () => {
  assert.throws(
    () =>
      assertNoPlaceholderSecrets(
        config({
          COOKIE_SECRET: "dev-only-change-me-0123456789abcdef0123456789abcdef",
        }),
      ),
    /COOKIE_SECRET/,
  );
});

test("an all-zero MASTER_ENCRYPTION_KEY refuses to boot in production", () => {
  assert.throws(
    () =>
      assertNoPlaceholderSecrets(
        config({ MASTER_ENCRYPTION_KEY: PLACEHOLDER_KEK }),
      ),
    (err: Error) => {
      assert.match(err.message, /MASTER_ENCRYPTION_KEY/);
      assert.match(err.message, /32 bytes hex/);
      return true;
    },
  );
});

test("every offending variable is reported at once, not one per restart", () => {
  assert.throws(
    () =>
      assertNoPlaceholderSecrets(
        config({
          INTERNAL_SHARED_SECRET: "dev-only-change-me-0123456789abcdef",
          COOKIE_SECRET: "dev-only-change-me-0123456789abcdef0123456789abcdef",
          MASTER_ENCRYPTION_KEY: PLACEHOLDER_KEK,
        }),
      ),
    (err: Error) => {
      for (const key of [
        "INTERNAL_SHARED_SECRET",
        "COOKIE_SECRET",
        "MASTER_ENCRYPTION_KEY",
      ]) {
        assert.match(err.message, new RegExp(key));
      }
      return true;
    },
  );
});

test("a user who edited the value at all is not blocked", () => {
  // Matching is on shape, not an exact string, so any real edit passes.
  assert.doesNotThrow(() =>
    assertNoPlaceholderSecrets(
      config({ INTERNAL_SHARED_SECRET: "my-own-secret-value-0123456789ab" }),
    ),
  );
});
