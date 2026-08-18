// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
import { loadConfig } from "./config.js";
import { initSentry } from "./observability.js";
import { buildServer } from "./server.js";

// Load .env in local dev. No-op (and harmless) when the file is absent, e.g.
// in production where config comes from the real environment. Existing
// process.env values take precedence over the file.
try {
  process.loadEnvFile();
} catch {
  /* no .env file — rely on the ambient environment */
}

async function main(): Promise<void> {
  const config = loadConfig();
  initSentry(config); // no-op unless SENTRY_DSN is set
  const { app } = await buildServer(config);

  try {
    await app.listen({ host: config.HOST, port: config.PORT });
  } catch (err) {
    app.log.error(err);
    process.exit(1);
  }

  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.on(signal, () => {
      app.log.info(`received ${signal}, shutting down`);
      void app.close().then(() => process.exit(0));
    });
  }
}

void main();
