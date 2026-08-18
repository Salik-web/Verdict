-- seed.sql — one demo account with competitors and prompts, for local testing.
--
-- Idempotent: fixed UUIDs + ON CONFLICT DO NOTHING, so it can be re-run safely.
-- Applied by the seed runner (apps/api: `pnpm db:seed`). NOT a migration —
-- never required by production.

-- Demo account ------------------------------------------------------------
-- plan=enterprise on purpose: this is the local demo/testing tenant, and the
-- test suites create scans against it too, so a low scans_per_day cap would make
-- the harness 429 on "Run scan" for reasons that have nothing to do with the app.
-- DO UPDATE (not DO NOTHING) so re-seeding converges an existing dev DB.
INSERT INTO accounts (id, name, slug, domain, brand_name, brand_aliases, plan, subscription_status)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'Acme Analytics',
  'acme-analytics',
  'acme.example.com',
  'Acme Analytics',
  ARRAY['Acme', 'AcmeAI'],
  'enterprise',
  'active'
)
ON CONFLICT (id) DO UPDATE SET plan = EXCLUDED.plan;

-- Owner user --------------------------------------------------------------
-- Deliberately NOT created here. A fixed password hash committed to a public
-- repository is a credential everyone on the internet knows, and "it's only the
-- demo account" stops being true the moment someone seeds a reachable
-- environment. The seed RUNNER (apps/api/src/db/seed.ts) creates this user with
-- a freshly generated password and prints it once.
--
--   pnpm --filter @geo/api db:seed

-- Competitors (incl. the account's own brand as is_self) -------------------
INSERT INTO competitors (id, account_id, name, domain, aliases, is_self)
VALUES
  ('00000000-0000-0000-0000-0000000000c0', '00000000-0000-0000-0000-000000000001',
   'Acme Analytics', 'acme.example.com', ARRAY['Acme', 'AcmeAI'], true),
  ('00000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-000000000001',
   'Globex Insights', 'globex.example.com', ARRAY['Globex'], false),
  ('00000000-0000-0000-0000-0000000000c2', '00000000-0000-0000-0000-000000000001',
   'Initech Metrics', 'initech.example.com', ARRAY['Initech'], false)
ON CONFLICT (id) DO NOTHING;

-- Prompts -----------------------------------------------------------------
INSERT INTO prompts (id, account_id, text, category, prompt_group, active)
VALUES
  ('00000000-0000-0000-0000-0000000000d1', '00000000-0000-0000-0000-000000000001',
   'What is the best product analytics tool for B2B SaaS?', 'recommendation', 'analytics-tools', true),
  ('00000000-0000-0000-0000-0000000000d2', '00000000-0000-0000-0000-000000000001',
   'Which analytics platforms support self-serve onboarding?', 'comparison', 'analytics-tools', true),
  ('00000000-0000-0000-0000-0000000000d3', '00000000-0000-0000-0000-000000000001',
   'Top alternatives to Globex Insights for product teams?', 'alternatives', 'competitive', true)
ON CONFLICT (id) DO NOTHING;

-- Verified facts (authoritative source of truth for generators) --------------
INSERT INTO verified_facts (id, account_id, fact_type, key, value, source, is_active)
VALUES
  ('00000000-0000-0000-0000-0000000000f1', '00000000-0000-0000-0000-000000000001',
   'pricing', 'starting_price', '{"display": "$0, usage-based"}',
   'https://acme.example.com/pricing', true),
  ('00000000-0000-0000-0000-0000000000f2', '00000000-0000-0000-0000-000000000001',
   'pricing', 'free_tier', '{"display": "1M events/mo free"}',
   'https://acme.example.com/pricing', true),
  ('00000000-0000-0000-0000-0000000000f3', '00000000-0000-0000-0000-000000000001',
   'feature', 'warehouse_native',
   '{"display": "Warehouse-native (BigQuery, Snowflake, Redshift)"}',
   'https://acme.example.com/features', true),
  ('00000000-0000-0000-0000-0000000000f4', '00000000-0000-0000-0000-000000000001',
   'feature', 'self_serve_onboarding', '{"display": "Self-serve onboarding"}',
   'https://acme.example.com/features', true),
  -- Competitor facts. `about`/`competitor` live in the jsonb value (no schema
  -- change). Claims about a rival are machine-checked against these exactly like
  -- claims about the customer, so a comparison page can only state a competitor's
  -- price if someone verified it and put it here.
  ('00000000-0000-0000-0000-0000000000f5', '00000000-0000-0000-0000-000000000001',
   'pricing', 'competitor_price',
   '{"display": "$99/mo", "about": "competitor", "competitor": "Globex Insights"}',
   'https://globex.example.com/pricing', true)
ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value, source = EXCLUDED.source;
