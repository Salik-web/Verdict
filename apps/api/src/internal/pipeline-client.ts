import { INTERNAL_SECRET_HEADER, type HealthResponse } from "@geo/shared";

export interface PipelineClientOptions {
  /** Base URL of the Python pipeline service, e.g. http://localhost:8000 */
  baseUrl: string;
  /** Shared secret sent on every internal call. */
  secret: string;
  /** Per-request timeout in milliseconds. */
  timeoutMs?: number;
}

export class PipelineClientError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "PipelineClientError";
  }
}

/**
 * Tiny typed client for the Python pipeline's internal HTTP endpoints.
 * Every request carries the INTERNAL_SHARED_SECRET header; the pipeline
 * rejects internal calls that miss or mismatch it.
 *
 * Phase 1 only exposes ping() — enough to prove the authenticated path works.
 * Trigger endpoints (monitor/diagnose/execute/verify) get added here later.
 */
export class PipelineClient {
  private readonly baseUrl: string;
  private readonly secret: string;
  private readonly timeoutMs: number;

  constructor(opts: PipelineClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.secret = opts.secret;
    this.timeoutMs = opts.timeoutMs ?? 5000;
  }

  /** Calls the pipeline's authenticated internal health endpoint. */
  async ping(): Promise<HealthResponse> {
    return this.request<HealthResponse>("GET", "/internal/ping");
  }

  /** Asks the pipeline to run a scan. The scan row must already exist. */
  async triggerScan(input: {
    scanId: string;
    accountId: string;
  }): Promise<ScanTriggerResponse> {
    return this.request<ScanTriggerResponse>("POST", "/internal/scans/run", {
      scan_id: input.scanId,
      account_id: input.accountId,
    });
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const res = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          [INTERNAL_SECRET_HEADER]: this.secret,
          ...(body !== undefined && { "content-type": "application/json" }),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      if (!res.ok) {
        throw new PipelineClientError(
          `Pipeline ${method} ${path} failed: ${res.status} ${res.statusText}`,
          res.status,
        );
      }
      return (await res.json()) as T;
    } catch (err) {
      if (err instanceof PipelineClientError) throw err;
      const reason = err instanceof Error ? err.message : String(err);
      throw new PipelineClientError(
        `Pipeline ${method} ${path} errored: ${reason}`,
      );
    } finally {
      clearTimeout(timer);
    }
  }
}

export interface ScanTriggerResponse {
  accepted: boolean;
  scan_id: string;
}
