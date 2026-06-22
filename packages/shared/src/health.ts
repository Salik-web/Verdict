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
