/**
 * Drizzle schema — a hand-written MIRROR of db/migrations/*.sql.
 *
 * The SQL is the single source of truth. When a migration changes the schema,
 * update this file (and the SQLAlchemy models in services/pipeline) to match.
 * Drizzle never generates the SQL here.
 */
import {
  bigint,
  boolean,
  index,
  integer,
  inet,
  jsonb,
  numeric,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uniqueIndex,
  uuid,
} from "drizzle-orm/pg-core";

// ── Enums (mirror CREATE TYPE ... AS ENUM) ─────────────────────────────
export const userRole = pgEnum("user_role", ["owner", "admin", "member"]);
export const scanStatus = pgEnum("scan_status", [
  "pending",
  "running",
  "completed",
  "failed",
  "canceled",
]);
export const jobStatus = pgEnum("job_status", [
  "queued",
  "running",
  "succeeded",
  "failed",
  "canceled",
]);
export const gapStatus = pgEnum("gap_status", [
  "open",
  "planned",
  "in_progress",
  "resolved",
  "dismissed",
]);
export const assetStatus = pgEnum("asset_status", [
  "draft",
  "generated",
  "validated",
  "published",
  "rejected",
]);
export const assetValidationState = pgEnum("asset_validation_state", [
  "pending",
  "passed",
  "failed",
]);
export const verificationVerdict = pgEnum("verification_verdict", [
  "improved",
  "no_change",
  "regressed",
  "inconclusive",
]);

// Reused column builders.
const createdAt = timestamp("created_at", { withTimezone: true })
  .notNull()
  .defaultNow();
const updatedAt = timestamp("updated_at", { withTimezone: true })
  .notNull()
  .defaultNow();

// ── accounts ───────────────────────────────────────────────────────────
export const accounts = pgTable(
  "accounts",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    name: text("name").notNull(),
    slug: text("slug").notNull(),
    domain: text("domain"),
    brandName: text("brand_name"),
    brandAliases: text("brand_aliases").array().notNull().default([]),
    plan: text("plan").notNull().default("free"),
    subscriptionStatus: text("subscription_status")
      .notNull()
      .default("trialing"),
    trialEndsAt: timestamp("trial_ends_at", { withTimezone: true }),
    currentPeriodEnd: timestamp("current_period_end", { withTimezone: true }),
    stripeCustomerId: text("stripe_customer_id"),
    stripeSubscriptionId: text("stripe_subscription_id"),
    settings: jsonb("settings").notNull().default({}),
    createdAt,
    updatedAt,
  },
  (t) => [uniqueIndex("accounts_slug_key").on(t.slug)],
);

// ── users ────────────────────────────────────────────────────────────────
export const users = pgTable(
  "users",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    email: text("email").notNull(),
    name: text("name"),
    role: userRole("role").notNull().default("member"),
    passwordHash: text("password_hash"),
    status: text("status").notNull().default("active"),
    lastLoginAt: timestamp("last_login_at", { withTimezone: true }),
    createdAt,
    updatedAt,
  },
  (t) => [index("users_account_id_idx").on(t.accountId)],
);

// ── competitors ────────────────────────────────────────────────────────
export const competitors = pgTable(
  "competitors",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    name: text("name").notNull(),
    domain: text("domain"),
    aliases: text("aliases").array().notNull().default([]),
    isSelf: boolean("is_self").notNull().default(false),
    createdAt,
    updatedAt,
  },
  (t) => [index("competitors_account_id_idx").on(t.accountId)],
);

// ── prompts ──────────────────────────────────────────────────────────────
export const prompts = pgTable(
  "prompts",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    text: text("text").notNull(),
    category: text("category"),
    promptGroup: text("prompt_group"),
    active: boolean("active").notNull().default(true),
    createdAt,
    updatedAt,
  },
  (t) => [
    index("prompts_account_id_idx").on(t.accountId),
    index("prompts_account_active_idx").on(t.accountId, t.active),
  ],
);

// ── scans ────────────────────────────────────────────────────────────────
export const scans = pgTable(
  "scans",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    status: scanStatus("status").notNull().default("pending"),
    engineSet: jsonb("engine_set").notNull().default([]),
    triggeredBy: text("triggered_by"),
    startedAt: timestamp("started_at", { withTimezone: true }),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
    stats: jsonb("stats").notNull().default({}),
    error: text("error"),
    createdAt,
    updatedAt,
  },
  (t) => [
    index("scans_account_id_idx").on(t.accountId),
    index("scans_account_status_idx").on(t.accountId, t.status),
  ],
);

// ── mentions (time-series, bigint identity PK) ─────────────────────────
export const mentions = pgTable(
  "mentions",
  {
    id: bigint("id", { mode: "bigint" })
      .primaryKey()
      .generatedAlwaysAsIdentity(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    scanId: uuid("scan_id")
      .notNull()
      .references(() => scans.id, { onDelete: "cascade" }),
    promptId: uuid("prompt_id")
      .notNull()
      .references(() => prompts.id, { onDelete: "cascade" }),
    engine: text("engine").notNull(),
    run: integer("run").notNull().default(1),
    brand: text("brand"),
    competitorId: uuid("competitor_id").references(() => competitors.id, {
      onDelete: "set null",
    }),
    mentioned: boolean("mentioned").notNull().default(false),
    position: integer("position"),
    sentiment: text("sentiment"),
    sentimentScore: numeric("sentiment_score"),
    citedUrls: jsonb("cited_urls").notNull().default([]),
    rawResponseRef: text("raw_response_ref"),
    createdAt,
    updatedAt,
  },
  (t) => [
    index("mentions_account_scan_idx").on(t.accountId, t.scanId),
    index("mentions_account_prompt_idx").on(t.accountId, t.promptId),
    index("mentions_account_brand_idx").on(t.accountId, t.brand),
  ],
);

// ── share_of_voice (precomputed aggregate) ─────────────────────────────
export const shareOfVoice = pgTable(
  "share_of_voice",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    scanId: uuid("scan_id")
      .notNull()
      .references(() => scans.id, { onDelete: "cascade" }),
    brand: text("brand").notNull(),
    competitorId: uuid("competitor_id").references(() => competitors.id, {
      onDelete: "set null",
    }),
    isSelf: boolean("is_self").notNull().default(false),
    engine: text("engine").notNull().default("all"),
    mentionCount: integer("mention_count").notNull().default(0),
    mentionRate: numeric("mention_rate"),
    avgPosition: numeric("avg_position"),
    sovPct: numeric("sov_pct"),
    details: jsonb("details").notNull().default({}),
    createdAt,
    updatedAt,
  },
  (t) => [
    uniqueIndex("sov_scan_brand_engine_key").on(
      t.accountId,
      t.scanId,
      t.brand,
      t.engine,
    ),
    index("sov_account_scan_idx").on(t.accountId, t.scanId),
  ],
);

// ── gaps ─────────────────────────────────────────────────────────────────
export const gaps = pgTable(
  "gaps",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    scanId: uuid("scan_id").references(() => scans.id, {
      onDelete: "set null",
    }),
    promptId: uuid("prompt_id").references(() => prompts.id, {
      onDelete: "set null",
    }),
    gapType: text("gap_type").notNull(),
    details: jsonb("details").notNull().default({}),
    rankScore: numeric("rank_score"),
    status: gapStatus("status").notNull().default("open"),
    createdAt,
    updatedAt,
  },
  (t) => [
    index("gaps_account_status_idx").on(t.accountId, t.status),
    index("gaps_account_scan_idx").on(t.accountId, t.scanId),
  ],
);

// ── assets ───────────────────────────────────────────────────────────────
export const assets = pgTable(
  "assets",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    gapId: uuid("gap_id").references(() => gaps.id, { onDelete: "set null" }),
    type: text("type").notNull(),
    title: text("title"),
    contentRef: text("content_ref"),
    metadata: jsonb("metadata").notNull().default({}),
    targetPromptIds: uuid("target_prompt_ids").array().notNull().default([]),
    status: assetStatus("status").notNull().default("draft"),
    validationState: assetValidationState("validation_state")
      .notNull()
      .default("pending"),
    createdAt,
    updatedAt,
  },
  (t) => [index("assets_account_status_idx").on(t.accountId, t.status)],
);

// ── verifications ──────────────────────────────────────────────────────
export const verifications = pgTable(
  "verifications",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    assetId: uuid("asset_id")
      .notNull()
      .references(() => assets.id, { onDelete: "cascade" }),
    scanBeforeId: uuid("scan_before_id").references(() => scans.id, {
      onDelete: "set null",
    }),
    scanAfterId: uuid("scan_after_id").references(() => scans.id, {
      onDelete: "set null",
    }),
    beforeMetrics: jsonb("before_metrics").notNull().default({}),
    afterMetrics: jsonb("after_metrics").notNull().default({}),
    confidence: numeric("confidence"),
    verdict: verificationVerdict("verdict").notNull().default("inconclusive"),
    createdAt,
    updatedAt,
  },
  (t) => [index("verifications_account_asset_idx").on(t.accountId, t.assetId)],
);

// ── verified_facts ─────────────────────────────────────────────────────
export const verifiedFacts = pgTable(
  "verified_facts",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    factType: text("fact_type").notNull(),
    key: text("key").notNull(),
    value: jsonb("value").notNull(),
    source: text("source"),
    confidence: numeric("confidence"),
    isActive: boolean("is_active").notNull().default(true),
    effectiveFrom: timestamp("effective_from", { withTimezone: true }),
    effectiveTo: timestamp("effective_to", { withTimezone: true }),
    createdAt,
    updatedAt,
  },
  (t) => [
    uniqueIndex("verified_facts_account_type_key_key").on(
      t.accountId,
      t.factType,
      t.key,
    ),
    index("verified_facts_account_type_idx").on(t.accountId, t.factType),
  ],
);

// ── jobs ─────────────────────────────────────────────────────────────────
export const jobs = pgTable(
  "jobs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    scanId: uuid("scan_id").references(() => scans.id, {
      onDelete: "set null",
    }),
    type: text("type").notNull(),
    status: jobStatus("status").notNull().default("queued"),
    payload: jsonb("payload").notNull().default({}),
    result: jsonb("result"),
    error: text("error"),
    attempts: integer("attempts").notNull().default(0),
    externalId: text("external_id"),
    startedAt: timestamp("started_at", { withTimezone: true }),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
    createdAt,
    updatedAt,
  },
  (t) => [
    index("jobs_account_status_idx").on(t.accountId, t.status),
    index("jobs_type_idx").on(t.type),
  ],
);

// ── audit_logs (append-only; created_at only) ──────────────────────────
export const auditLogs = pgTable(
  "audit_logs",
  {
    id: bigint("id", { mode: "bigint" })
      .primaryKey()
      .generatedAlwaysAsIdentity(),
    accountId: uuid("account_id").references(() => accounts.id, {
      onDelete: "set null",
    }),
    actorType: text("actor_type").notNull(),
    actorId: text("actor_id"),
    action: text("action").notNull(),
    resourceType: text("resource_type"),
    resourceId: text("resource_id"),
    metadata: jsonb("metadata").notNull().default({}),
    ip: inet("ip"),
    createdAt,
  },
  (t) => [index("audit_logs_account_created_idx").on(t.accountId, t.createdAt)],
);

// ── llm_cost_log (append-only; created_at only) ────────────────────────
export const llmCostLog = pgTable(
  "llm_cost_log",
  {
    id: bigint("id", { mode: "bigint" })
      .primaryKey()
      .generatedAlwaysAsIdentity(),
    accountId: uuid("account_id")
      .notNull()
      .references(() => accounts.id, { onDelete: "cascade" }),
    jobId: uuid("job_id").references(() => jobs.id, { onDelete: "set null" }),
    scanId: uuid("scan_id").references(() => scans.id, {
      onDelete: "set null",
    }),
    provider: text("provider").notNull(),
    model: text("model").notNull(),
    operation: text("operation"),
    promptTokens: integer("prompt_tokens").notNull().default(0),
    completionTokens: integer("completion_tokens").notNull().default(0),
    totalTokens: integer("total_tokens").notNull().default(0),
    costUsd: numeric("cost_usd", { precision: 12, scale: 6 })
      .notNull()
      .default("0"),
    mock: boolean("mock").notNull().default(false),
    createdAt,
  },
  (t) => [
    index("llm_cost_log_account_created_idx").on(t.accountId, t.createdAt),
    index("llm_cost_log_model_idx").on(t.model),
  ],
);
