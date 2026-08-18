// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Plan usage quota for pipeline work — the cost cap.
 *
 * Shared by POST /scans and the per-stage triggers so "re-run a stage" can't be
 * used to bypass the gate. Keyed to the account's plan (config/plans.json) and
 * counted as scans created today (UTC).
 */
import type { AppContext } from "./context.js";
import { limitsFor } from "./plans.js";
import { AccountRepository } from "./repositories/account-repository.js";
import { ScanRepository } from "./repositories/scan-repository.js";

export type QuotaState =
  | { ok: true }
  | { ok: false; limit: number; used: number; retryAfter: number };

function startOfTodayUtc(): Date {
  const d = new Date();
  d.setUTCHours(0, 0, 0, 0);
  return d;
}

export function secondsToMidnightUtc(): number {
  const now = new Date();
  return Math.ceil(
    (Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate() + 1,
    ) -
      Date.now()) /
      1000,
  );
}

export async function checkScanQuota(
  ctx: AppContext,
  accountId: string,
): Promise<QuotaState> {
  const account = await new AccountRepository(ctx.db).findById(accountId);
  const limits = limitsFor(account?.plan ?? "free");
  const used = await new ScanRepository(ctx.db).countSince(
    accountId,
    startOfTodayUtc(),
  );
  if (used >= limits.scans_per_day) {
    return {
      ok: false,
      limit: limits.scans_per_day,
      used,
      retryAfter: secondsToMidnightUtc(),
    };
  }
  return { ok: true };
}
