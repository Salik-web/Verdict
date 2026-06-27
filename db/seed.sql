-- seed.sql — one demo account with competitors and prompts, for local testing.
--
-- Idempotent: fixed UUIDs + ON CONFLICT DO NOTHING, so it can be re-run safely.
-- Applied by the seed runner (apps/api: `pnpm db:seed`). NOT a migration —
-- never required by production.

-- Demo account ------------------------------------------------------------
INSERT INTO accounts (id, name, slug, domain, brand_name, brand_aliases, plan, subscription_status)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'Acme Analytics',
  'acme-analytics',
  'acme.example.com',
  'Acme Analytics',
  ARRAY['Acme', 'AcmeAI'],
  'pro',
  'active'
)
ON CONFLICT (id) DO NOTHING;

-- Owner user --------------------------------------------------------------
INSERT INTO users (id, account_id, email, name, role, status)
VALUES (
  '00000000-0000-0000-0000-0000000000a1',
  '00000000-0000-0000-0000-000000000001',
  'owner@acme.example.com',
  'Acme Owner',
  'owner',
  'active'
)
ON CONFLICT (id) DO NOTHING;

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
