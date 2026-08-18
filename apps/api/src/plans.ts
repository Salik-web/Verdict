// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Salik Syed
/**
 * Typed loader for config/plans.json — per-plan usage quotas.
 * Data-driven: limits change in the JSON, never in code.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

const planSchema = z.object({
  scans_per_day: z.number().int().positive(),
  api_rpm: z.number().int().positive(),
  max_prompts: z.number().int().positive(),
  max_competitors: z.number().int().positive(),
});

const plansFileSchema = z.object({
  plans: z.record(planSchema),
  default_plan: z.string(),
});

export type PlanLimits = z.infer<typeof planSchema>;

const here = path.dirname(fileURLToPath(import.meta.url));
const PLANS_PATH = path.resolve(here, "../config/plans.json");

let cached: z.infer<typeof plansFileSchema> | undefined;

export function loadPlans(): z.infer<typeof plansFileSchema> {
  cached ??= plansFileSchema.parse(
    JSON.parse(readFileSync(PLANS_PATH, "utf8")),
  );
  return cached;
}

/** Unknown plan names fall back to the default plan's limits. */
export function limitsFor(plan: string): PlanLimits {
  const { plans, default_plan } = loadPlans();
  return plans[plan] ?? plans[default_plan]!;
}
