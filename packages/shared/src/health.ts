// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Health-check contract shared by both services.
 * Mirrors ./schemas/health.schema.json.
 */

export type HealthState = "ok" | "degraded";

export interface HealthResponse {
  /** Overall service state. */
  status: HealthState;
  /** Logical service name, e.g. "api" or "pipeline". */
  service: string;
  /** Service semantic version. */
  version: string;
  /** ISO-8601 timestamp the response was produced. */
  time: string;
}
