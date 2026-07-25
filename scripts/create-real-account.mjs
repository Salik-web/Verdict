#!/usr/bin/env node
// Create a REAL test account (real domain, real competitors, real prompts, real
// verified facts incl. competitor facts) by driving the actual API — same path
// the UI takes, so whatever this produces is what the product would produce.
//
//   node scripts/create-real-account.mjs scripts/real-account.json
//
// Refuses to run while any FILL_ME remains: a comparison page is only as honest
// as its facts, and an unchecked "fact" becomes a claim on a customer's page.

import { readFileSync } from "node:fs";

const API = process.env.API_BASE_URL ?? "http://localhost:3000";
const file = process.argv[2];

if (!file) {
  console.error("usage: node scripts/create-real-account.mjs <config.json>");
  console.error("start from scripts/real-account.example.json");
  process.exit(1);
}

const cfg = JSON.parse(readFileSync(file, "utf8"));
delete cfg._readme;

// ── refuse placeholders ──────────────────────────────────────────────────
const placeholders = [];
(function scan(node, path) {
  if (typeof node === "string") {
    if (node.includes("FILL_ME")) placeholders.push(path);
  } else if (Array.isArray(node)) {
    node.forEach((v, i) => scan(v, `${path}[${i}]`));
  } else if (node && typeof node === "object") {
    for (const [k, v] of Object.entries(node)) scan(v, path ? `${path}.${k}` : k);
  }
})(cfg, "");

if (placeholders.length) {
  console.error(`\n${file} still has ${placeholders.length} FILL_ME value(s):\n`);
  for (const p of placeholders) console.error(`  - ${p}`);
  console.error(
    "\nFill them in with values you have actually verified, then re-run.\n" +
      "Competitor facts especially: read the competitor's real pricing page.\n" +
      "This is the difference between a page that states facts and one that invents them.\n",
  );
  process.exit(1);
}

// ── require the fields the pipeline can't run without ────────────────────
// FILL_ME-only validation missed the real trap: an empty or missing `domain`
// isn't a placeholder, so it sailed through — and an account with no domain has
// Diagnosis skip ("no domain to diagnose"), which silently empties gaps/assets/
// proof. Fail loudly here instead of one empty page at a time.
const REQUIRED = ["email", "password", "accountName", "domain", "brandName"];
const missing = REQUIRED.filter(
  (k) => typeof cfg[k] !== "string" || cfg[k].trim() === "",
);
if (missing.length) {
  console.error(
    `\n${file} is missing required value(s): ${missing.join(", ")}\n` +
      "domain and brandName are not optional: without a domain Diagnosis is\n" +
      "skipped, so the scan produces no gaps, no assets, and nothing to verify.\n",
  );
  process.exit(1);
}

// ── tiny API client (session cookie, loud errors) ────────────────────────
let COOKIE = "";
async function call(method, path, body) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      ...(body ? { "content-type": "application/json" } : {}),
      ...(COOKIE ? { cookie: COOKIE } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const setCookie = res.headers.getSetCookie?.() ?? [];
  if (setCookie.length) COOKIE = setCookie.map((c) => c.split(";")[0]).join("; ");
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    throw new Error(
      `${method} ${path} -> HTTP ${res.status}\n${JSON.stringify(data, null, 2)}`,
    );
  }
  return data;
}

// ── run ──────────────────────────────────────────────────────────────────
try {
  await fetch(`${API}/health`);
} catch {
  console.error(`Cannot reach the API at ${API}. Is it running?`);
  process.exit(1);
}

console.log(`API: ${API}`);

const signup = await call("POST", "/auth/signup", {
  email: cfg.email,
  password: cfg.password,
  accountName: cfg.accountName,
}).catch((err) => {
  if (String(err).includes("email_taken")) {
    console.error(
      `\nThat email already has an account. Use a new email, or log in as it.\n`,
    );
    process.exit(1);
  }
  throw err;
});
console.log(`✓ account ${signup.accountId}  (user ${signup.userId})`);

await call("PATCH", "/account", {
  domain: cfg.domain,
  brandName: cfg.brandName,
  brandAliases: cfg.brandAliases ?? [],
});
console.log(`✓ brand "${cfg.brandName}" @ ${cfg.domain}`);

// The account's own brand must exist as a competitor with isSelf, or
// share-of-voice can't tell which row is you.
await call("POST", "/competitors", {
  name: cfg.brandName,
  domain: cfg.domain,
  aliases: cfg.brandAliases ?? [],
  isSelf: true,
});
console.log(`✓ self competitor "${cfg.brandName}"`);

for (const c of cfg.competitors ?? []) {
  await call("POST", "/competitors", {
    name: c.name,
    domain: c.domain,
    aliases: c.aliases ?? [],
    isSelf: false,
  });
  console.log(`✓ competitor "${c.name}"`);
}

for (const p of cfg.prompts ?? []) {
  await call("POST", "/prompts", { text: p.text, category: p.category });
  console.log(`✓ prompt [${p.category}] ${p.text.slice(0, 60)}`);
}

let selfFacts = 0;
let competitorFacts = 0;
for (const f of cfg.verifiedFacts ?? []) {
  await call("POST", "/verified-facts", {
    factType: f.factType,
    key: f.key,
    value: f.value,
    source: f.source,
  });
  if (f.value?.about === "competitor") competitorFacts++;
  else selfFacts++;
  console.log(`✓ fact ${f.factType}/${f.key} (${f.value?.about ?? "self"})`);
}

// ── what this will cost when you scan ────────────────────────────────────
const REPEATS = 5; // services/pipeline/config/monitor.yaml
const prompts = (cfg.prompts ?? []).length;
const grounded = prompts * REPEATS;

console.log(`
─────────────────────────────────────────────────────────────
Account ready: ${signup.accountId}
  login          ${cfg.email}
  self facts     ${selfFacts}
  competitor facts ${competitorFacts}${competitorFacts === 0 ? "  <-- page will refuse to state competitor data" : ""}

A scan on this account will make roughly:
  ${grounded} grounded Gemini calls (measurement: ${prompts} prompts x ${REPEATS} repeats)
  ${grounded} cheap parse calls
  1 generation call
Grounded calls are billed/quota'd separately from tokens, and spacing between
them is deliberate — expect the scan to take minutes, not seconds.

Next:
  1. GATEWAY_MODE=dev + GOOGLE_API_KEY in services/pipeline/.env, restart the
     pipeline AND the celery worker (they read env at boot).
  2. Log into the harness at http://localhost:5173 as ${cfg.email}
  3. /setup -> Run scan, then watch /scans.
─────────────────────────────────────────────────────────────`);
