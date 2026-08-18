// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
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

  /** Generates a buyer-intent prompt pack for an account and stores it.
   *
   * Synchronous upstream (one model call), so this needs a longer timeout than
   * the fire-and-forget triggers above: it returns the prompts themselves, not
   * a task id. */
  async generatePrompts(input: {
    accountId: string;
    count?: number;
    category?: string;
  }): Promise<PromptGenerateResponse> {
    return this.request<PromptGenerateResponse>(
      "POST",
      "/internal/prompts/generate",
      {
        account_id: input.accountId,
        count: input.count ?? null,
        category: input.category ?? null,
      },
      { timeoutMs: 120_000 },
    );
  }

  /** Read-only engine availability for this deployment. */
  async engines(): Promise<EnginesResponse> {
    return this.request<EnginesResponse>("GET", "/internal/engines");
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
    opts?: { timeoutMs?: number },
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(
      () => controller.abort(),
      opts?.timeoutMs ?? this.timeoutMs,
    );
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
        // Carry the upstream detail: a 503 here means a provider key is missing,
        // and "set PERPLEXITY_API_KEY" is the only useful thing to tell the user.
        // Never let a body-parse failure mask the real status.
        let detail = "";
        try {
          const parsed = (await res.json()) as { detail?: unknown };
          if (typeof parsed?.detail === "string") detail = ` — ${parsed.detail}`;
        } catch {
          /* non-JSON body; the status line is all we have */
        }
        throw new PipelineClientError(
          `Pipeline ${method} ${path} failed: ${res.status} ${res.statusText}${detail}`,
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

export interface PromptGenerateResponse {
  generated: number;
  created: number;
  skipped_duplicates: number;
  prompts: { id: string; text: string }[];
}

export interface EngineStatus {
  task: string;
  label: string;
  provider: string;
  model: string;
  available: boolean;
  reason: string | null;
  missing_key_env: string | null;
  is_measurement: boolean;
}

export interface EnginesResponse {
  mode: string;
  engines: EngineStatus[];
}
