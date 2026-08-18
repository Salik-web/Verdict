// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * AppContext — everything routes need, built once in server.ts and passed
 * down. Keeps routes free of construction logic and easy to test with fakes.
 */
import type { Redis } from "ioredis";
import type { AuthService } from "./auth/service.js";
import type { SessionStore } from "./auth/session-store.js";
import type { AppConfig } from "./config.js";
import type { Envelope } from "./crypto/envelope.js";
import type { Database } from "./db/client.js";
import type { PipelineClient } from "./internal/pipeline-client.js";

export interface AppContext {
  config: AppConfig;
  db: Database;
  redis: Redis;
  sessions: SessionStore;
  auth: AuthService;
  envelope: Envelope;
  pipeline: PipelineClient;
}
