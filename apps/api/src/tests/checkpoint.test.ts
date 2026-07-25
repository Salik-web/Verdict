/**
 * Phase 4 checkpoint (node:test + app.inject against live Postgres/Redis,
 * plus the live Python pipeline for POST /scans):
 *
 *   signup -> login -> create competitors+prompts -> POST /scans reaches the
 *   pipeline; cross-tenant access is blocked; secrets are never echoed.
 *
 * Run: pnpm --filter @geo/api test   (infra + pipeline must be running)
 */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { after, before, describe, it } from "node:test";
import { resolveArtifactPath } from "../artifacts.js";
import { type AppConfig, loadConfig } from "../config.js";
import { assets, verifications } from "../db/schema.js";
import { buildServer } from "../server.js";

// Loads apps/api/.env (cwd when run via `pnpm --filter @geo/api test`).
try {
  process.loadEnvFile();
} catch {
  /* fall back to ambient env */
}

const run = Date.now().toString(36);
// Unique per-run "client IPs" so auth rate limits never collide across runs.
const ipA = { "x-forwarded-for": `10.1.${Math.floor(Math.random() * 250)}.1` };
const ipB = { "x-forwarded-for": `10.2.${Math.floor(Math.random() * 250)}.2` };

type Built = Awaited<ReturnType<typeof buildServer>>;
let app: Built["app"];
let ctx: Built["ctx"];
let config: AppConfig;

function cookieHeader(res: {
  cookies: Array<{ name: string; value: string }>;
}) {
  return res.cookies.map((c) => `${c.name}=${c.value}`).join("; ");
}

describe("phase 4 checkpoint", async () => {
  let cookieA = "";
  let cookieB = "";
  let competitorId = "";
  let scanId = "";
  let accountIdA = "";

  before(async () => {
    config = loadConfig();
    ({ app, ctx } = await buildServer(config));
    await app.ready();
  });
  after(async () => {
    await app.close();
  });

  it("signs up two users in two tenants", async () => {
    const a = await app.inject({
      method: "POST",
      url: "/auth/signup",
      headers: ipA,
      payload: {
        email: `alice-${run}@test.dev`,
        password: "correct-horse-battery",
        accountName: `Tenant A ${run}`,
      },
    });
    assert.equal(a.statusCode, 201);
    cookieA = cookieHeader(a);
    accountIdA = a.json().accountId;
    assert.match(cookieA, /geo_session=/);

    const b = await app.inject({
      method: "POST",
      url: "/auth/signup",
      headers: ipB,
      payload: {
        email: `bob-${run}@test.dev`,
        password: "correct-horse-battery",
        accountName: `Tenant B ${run}`,
      },
    });
    assert.equal(b.statusCode, 201);
    cookieB = cookieHeader(b);
  });

  it("logs in and reads /auth/me", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/auth/login",
      headers: ipA,
      payload: {
        email: `alice-${run}@test.dev`,
        password: "correct-horse-battery",
      },
    });
    assert.equal(res.statusCode, 200);
    cookieA = cookieHeader(res);

    const me = await app.inject({
      method: "GET",
      url: "/auth/me",
      headers: { cookie: cookieA },
    });
    assert.equal(me.statusCode, 200);
    assert.equal(me.json().email, `alice-${run}@test.dev`);
  });

  it("rejects wrong passwords and anonymous access", async () => {
    const bad = await app.inject({
      method: "POST",
      url: "/auth/login",
      headers: ipA,
      payload: { email: `alice-${run}@test.dev`, password: "wrong-password!" },
    });
    assert.equal(bad.statusCode, 401);

    const anon = await app.inject({ method: "GET", url: "/competitors" });
    assert.equal(anon.statusCode, 401);
  });

  it("creates competitors and prompts for tenant A", async () => {
    const comp = await app.inject({
      method: "POST",
      url: "/competitors",
      headers: { cookie: cookieA },
      payload: { name: "Globex", domain: "globex.example.com" },
    });
    assert.equal(comp.statusCode, 201);
    competitorId = comp.json().id;

    const prompt = await app.inject({
      method: "POST",
      url: "/prompts",
      headers: { cookie: cookieA },
      payload: { text: "Best product analytics tool for B2B SaaS?" },
    });
    assert.equal(prompt.statusCode, 201);
  });

  it("validates input with zod (400 on garbage)", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/prompts",
      headers: { cookie: cookieA },
      payload: { text: "x" }, // below min length
    });
    assert.equal(res.statusCode, 400);
    assert.equal(res.json().error, "invalid_request");
  });

  it("BLOCKS cross-tenant access (B cannot see A's data)", async () => {
    const direct = await app.inject({
      method: "GET",
      url: `/competitors/${competitorId}`,
      headers: { cookie: cookieB },
    });
    assert.equal(direct.statusCode, 404); // scoped lookup: not found, not leaked

    const patch = await app.inject({
      method: "PATCH",
      url: `/competitors/${competitorId}`,
      headers: { cookie: cookieB },
      payload: { name: "hijacked" },
    });
    assert.equal(patch.statusCode, 404);

    const list = await app.inject({
      method: "GET",
      url: "/competitors",
      headers: { cookie: cookieB },
    });
    assert.equal(list.statusCode, 200);
    assert.equal(list.json().length, 0); // B's tenant is empty
  });

  it("POST /scans creates a row and reaches the Python pipeline", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/scans",
      headers: { cookie: cookieA },
      payload: { engines: ["chatgpt", "perplexity"] },
    });
    assert.equal(
      res.statusCode,
      202,
      `expected 202, got ${res.statusCode}: ${res.body} — is the Python service running?`,
    );
    scanId = res.json().scanId;
    assert.ok(scanId);

    const fetched = await app.inject({
      method: "GET",
      url: `/scans/${scanId}`,
      headers: { cookie: cookieA },
    });
    assert.equal(fetched.statusCode, 200);
    // POST /scans now runs the whole chain, so if a Celery worker is up the scan
    // may already have moved on — any live lifecycle state is correct here.
    assert.ok(
      ["pending", "running", "completed"].includes(fetched.json().status),
      `unexpected scan status: ${fetched.json().status}`,
    );
  });

  it("triggers individual stages, tenant-scoped and quota-checked", async () => {
    // Re-run ONE stage without a full scan. Tenant A has 1 scan today (limit 2),
    // so the quota gate passes; the gate itself is proven by the quota test next.
    const diagnose = await app.inject({
      method: "POST",
      url: `/scans/${scanId}/diagnose`,
      headers: { cookie: cookieA },
    });
    assert.equal(
      diagnose.statusCode,
      202,
      `expected 202, got ${diagnose.statusCode}: ${diagnose.body} — is the Python service running?`,
    );

    const execute = await app.inject({
      method: "POST",
      url: `/scans/${scanId}/execute`,
      headers: { cookie: cookieA },
    });
    assert.equal(execute.statusCode, 202);

    // Cross-tenant: B cannot re-run a stage on A's scan (404, not a leak).
    const crossStage = await app.inject({
      method: "POST",
      url: `/scans/${scanId}/diagnose`,
      headers: { cookie: cookieB },
    });
    assert.equal(crossStage.statusCode, 404);

    // The verify trigger is asset-scoped (it forces the scheduled re-measure).
    const assetId = randomUUID();
    await ctx.db.insert(assets).values({
      id: assetId,
      accountId: accountIdA,
      type: "comparison_page",
      title: "Trigger fixture",
      status: "validated",
      validationState: "passed",
      targetPromptIds: [],
      metadata: {},
    });
    const verify = await app.inject({
      method: "POST",
      url: `/assets/${assetId}/verify`,
      headers: { cookie: cookieA },
    });
    assert.equal(verify.statusCode, 202);

    const crossVerify = await app.inject({
      method: "POST",
      url: `/assets/${assetId}/verify`,
      headers: { cookie: cookieB },
    });
    assert.equal(crossVerify.statusCode, 404);
  });

  it("blocks cross-tenant scan reads and enforces the plan quota", async () => {
    const cross = await app.inject({
      method: "GET",
      url: `/scans/${scanId}`,
      headers: { cookie: cookieB },
    });
    assert.equal(cross.statusCode, 404);

    // free plan: 2 scans/day. One used; second passes, third must 429.
    const second = await app.inject({
      method: "POST",
      url: "/scans",
      headers: { cookie: cookieA },
      payload: {},
    });
    assert.equal(second.statusCode, 202);

    const third = await app.inject({
      method: "POST",
      url: "/scans",
      headers: { cookie: cookieA },
      payload: {},
    });
    assert.equal(third.statusCode, 429);
    assert.equal(third.json().error, "quota_exceeded");
    assert.ok(
      Number(third.headers["retry-after"]) > 0,
      "Retry-After header set",
    );
  });

  it("stores CMS credentials encrypted and never echoes them", async () => {
    const res = await app.inject({
      method: "POST",
      url: "/cms-credentials",
      headers: { cookie: cookieA },
      payload: {
        cmsType: "wordpress",
        name: "Main blog",
        credentials: {
          url: "https://blog.example.com",
          app_password: "s3cr3t-value",
        },
      },
    });
    assert.equal(res.statusCode, 201);
    const body = res.body;
    assert.ok(!body.includes("s3cr3t-value"), "secret must not be echoed");
    assert.ok(!body.includes("ciphertext"), "ciphertext must not be returned");

    const list = await app.inject({
      method: "GET",
      url: "/cms-credentials",
      headers: { cookie: cookieA },
    });
    assert.equal(list.statusCode, 200);
    assert.ok(!list.body.includes("s3cr3t-value"));
  });

  it("serves a single asset with its content + tenant-scoped verifications", async () => {
    // Seed an asset + its on-disk content + a verification (the pipeline writes
    // these; here we insert directly to test the read endpoints deterministically).
    const assetId = randomUUID();
    const contentRef = `artifacts/${accountIdA}/${assetId}.html`;
    const html = "<h1>Acme vs Globex</h1><p>Seeded asset body.</p>";
    const full = resolveArtifactPath(config, accountIdA, assetId, contentRef);
    await mkdir(path.dirname(full), { recursive: true });
    await writeFile(full, html, "utf8");

    await ctx.db.insert(assets).values({
      id: assetId,
      accountId: accountIdA,
      type: "comparison_page",
      title: "Acme vs Globex",
      contentRef,
      status: "validated",
      validationState: "passed",
      targetPromptIds: [],
      metadata: {},
    });
    const [ver] = await ctx.db
      .insert(verifications)
      .values({
        accountId: accountIdA,
        assetId,
        verdict: "improved",
        confidence: "0.62",
        beforeMetrics: { mention_rate: 0 },
        afterMetrics: { mention_rate: 0.6 },
      })
      .returning();
    assert.ok(ver);

    // GET /assets/:id — row + file content, tenant-scoped.
    const asset = await app.inject({
      method: "GET",
      url: `/assets/${assetId}`,
      headers: { cookie: cookieA },
    });
    assert.equal(asset.statusCode, 200);
    assert.equal(asset.json().type, "comparison_page");
    assert.match(asset.json().content, /Seeded asset body/);
    assert.equal(asset.json().contentError, null);

    // Cross-tenant asset read is a 404 (not a leak, and no file access).
    const crossAsset = await app.inject({
      method: "GET",
      url: `/assets/${assetId}`,
      headers: { cookie: cookieB },
    });
    assert.equal(crossAsset.statusCode, 404);

    // GET /verifications (list + by id), tenant-scoped.
    const list = await app.inject({
      method: "GET",
      url: "/verifications",
      headers: { cookie: cookieA },
    });
    assert.equal(list.statusCode, 200);
    assert.ok(list.json().some((v: { id: string }) => v.id === ver.id));

    const one = await app.inject({
      method: "GET",
      url: `/verifications/${ver.id}`,
      headers: { cookie: cookieA },
    });
    assert.equal(one.statusCode, 200);
    assert.equal(one.json().verdict, "improved");

    // Cross-tenant: B's list is empty and the direct read is 404.
    const crossList = await app.inject({
      method: "GET",
      url: "/verifications",
      headers: { cookie: cookieB },
    });
    assert.equal(crossList.json().length, 0);
    const crossOne = await app.inject({
      method: "GET",
      url: `/verifications/${ver.id}`,
      headers: { cookie: cookieB },
    });
    assert.equal(crossOne.statusCode, 404);
  });

  it("refresh rotation works and reused tokens are rejected", async () => {
    const login = await app.inject({
      method: "POST",
      url: "/auth/login",
      headers: ipA,
      payload: {
        email: `alice-${run}@test.dev`,
        password: "correct-horse-battery",
      },
    });
    const refreshCookie = login.cookies.find((c) => c.name === "geo_refresh")!;
    const doRefresh = () =>
      app.inject({
        method: "POST",
        url: "/auth/refresh",
        headers: { cookie: `geo_refresh=${refreshCookie.value}` },
      });

    const first = await doRefresh();
    assert.equal(first.statusCode, 200); // rotated

    const replay = await doRefresh();
    assert.equal(replay.statusCode, 401); // same token again -> rejected
  });

  it("sets security headers and locks CORS", async () => {
    const res = await app.inject({
      method: "GET",
      url: "/health",
      headers: { origin: "https://evil.example.com" },
    });
    assert.ok(res.headers["strict-transport-security"]);
    assert.equal(res.headers["x-frame-options"], "DENY");
    assert.notEqual(
      res.headers["access-control-allow-origin"],
      "https://evil.example.com",
    );
  });
});
