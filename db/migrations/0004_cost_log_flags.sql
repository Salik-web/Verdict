-- ---------------------------------------------------------------------------
-- 0004_cost_log_flags — make llm_cost_log a COMPLETE ledger.
--
-- Every gateway call must leave exactly one row, including the ones that never
-- hit a provider. Two new flags distinguish them so the pricing model can filter:
--   cached  — served from the response cache; no provider call, cost_usd = 0.
--   status  — 'ok' for a completed call, 'error' for one that raised (after any
--             fallback). Failed calls are logged with zero usage/cost and status
--             'error', so a gap in the ledger means a logging bug, never a
--             silently-swallowed call.
-- Backfill: existing rows are completed, real, uncached calls -> ('ok', false).
-- ---------------------------------------------------------------------------

ALTER TABLE llm_cost_log
  ADD COLUMN cached boolean NOT NULL DEFAULT false,
  ADD COLUMN status text NOT NULL DEFAULT 'ok';

-- Query pattern for "actual spend" vs "logical calls": spend filters cached=false.
CREATE INDEX llm_cost_log_status_idx ON llm_cost_log (status);
