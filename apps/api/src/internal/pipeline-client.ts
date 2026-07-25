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
 * triggerScan() runs the FULL pipeline chain (monitor -> diagnose -> plan+
 * execute). The per-stage triggers exist to re-run one stage without a whole
 * scan. Verification is deliberately not part of the chain — the pipeline's beat
 * schedules it after a configured delay — but triggerVerification() forces it now.
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

  /**
   * Runs the full pipeline for a scan: monitor -> diagnose -> plan+execute.
   * The scan row must already exist.
   */
  async triggerScan(input: {
    scanId: string;
    accountId: string;
  }): Promise<ScanTriggerResponse> {
    return this.request<ScanTriggerResponse>("POST", "/internal/scans/run", {
      scan_id: input.scanId,
      account_id: input.accountId,
    });
  }

  /** Re-runs ONLY the Diagnosis stage against an existing scan. */
  async triggerDiagnosis(input: {
    scanId: string;
    accountId: string;
  }): Promise<ScanTriggerResponse> {
    return this.request<ScanTriggerResponse>("POST", "/internal/diagnoses/run", {
      scan_id: input.scanId,
      account_id: input.accountId,
    });
  }

  /** Re-runs ONLY the Plan+Execute stage against an existing scan. */
  async triggerExecution(input: {
    scanId: string;
    accountId: string;
  }): Promise<ScanTriggerResponse> {
    return this.request<ScanTriggerResponse>(
      "POST",
      "/internal/executions/run",
      { scan_id: input.scanId, account_id: input.accountId },
    );
  }

  /** Forces the verification re-measure for one shipped asset, ignoring the
   * scheduled delay (the beat would otherwise pick it up when it comes due). */
  async triggerVerification(input: {
    assetId: string;
    accountId: string;
  }): Promise<VerificationTriggerResponse> {
    return this.request<VerificationTriggerResponse>(
      "POST",
      "/internal/verifications/run",
      { asset_id: input.assetId, account_id: input.accountId },
    );
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
  task_id?: string | null;
}

export interface VerificationTriggerResponse {
  accepted: boolean;
  asset_id: string;
  task_id?: string | null;
}
