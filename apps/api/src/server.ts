import Fastify, { type FastifyInstance } from "fastify";
import type { HealthResponse } from "@geo/shared";
import { createRequire } from "node:module";
import type { AppConfig } from "./config.js";
import { PipelineClient } from "./internal/pipeline-client.js";

const require = createRequire(import.meta.url);
const { version: SERVICE_VERSION } = require("../package.json") as {
  version: string;
};

/**
 * Builds the Fastify app. Kept separate from the listen() entrypoint so tests
 * can use app.inject() without binding a port.
 */
export function buildServer(config: AppConfig): FastifyInstance {
  const app = Fastify({
    logger: { level: config.LOG_LEVEL },
  });

  const pipeline = new PipelineClient({
    baseUrl: config.PIPELINE_URL,
    secret: config.INTERNAL_SHARED_SECRET,
  });

  // Public health check — no auth, used by Docker/load balancers.
  app.get("/health", async (): Promise<HealthResponse> => {
    return {
      status: "ok",
      service: "api",
      version: SERVICE_VERSION,
      time: new Date().toISOString(),
    };
  });

  // Proves the authenticated internal path: the API reaches the Python
  // pipeline's protected /internal/ping using the shared-secret client.
  app.get("/internal/pipeline-health", async (_req, reply) => {
    try {
      const pong = await pipeline.ping();
      return { status: "ok", pipeline: pong } as const;
    } catch (err) {
      app.log.error({ err }, "pipeline ping failed");
      return reply
        .code(502)
        .send({ status: "error", message: "pipeline unreachable" });
    }
  });

  return app;
}
