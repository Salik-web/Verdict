-- ---------------------------------------------------------------------------
-- LEDGER CORRECTION — 2026-07-25
--
-- llm_cost_log is append-only by design, so this file exists to make a deletion
-- auditable rather than silent. It is NOT a migration (no schema change) and is
-- not run by db:migrate; it is a one-off, already-applied record of a manual
-- correction to a development database.
--
-- WHAT WAS REMOVED
--   6 rows (id 637-642), scan c1f854e5-a7b7-463f-942e-057c2e950266,
--   operation 'processing', 2026-07-24 12:07:42 - 12:07:45 UTC.
--   3 real calls totalling $0.000218 + 3 cache hits at $0.
--
-- WHY
--   These were produced by an ABORTED re-parse attempt during development: the
--   run crashed mid-way on a schema-validation error (ParsedMention rejected
--   extra fields returned by the live judge model) and wrote no mentions/SoV.
--   The calls were real, but they are debugging artifacts of the tooling, not
--   work the scan performed — leaving them in makes scan c1f854e5 unusable as a
--   reference figure for per-scan cost modelling.
--
-- WHAT WAS KEPT
--   - The original grounded run (2026-07-23), including its known-incomplete
--     rows: that is the historical record of the old buggy code and is not
--     rewritten here.
--   - The SUCCESSFUL re-parse batch (2026-07-24 12:08:31-12:08:36, 10 rows:
--     4 real + 6 cached), which is the work that produced the current data.
--
-- An audit_logs entry is written alongside so the correction is discoverable
-- from the database itself, not only from this file.
-- ---------------------------------------------------------------------------

BEGIN;

INSERT INTO audit_logs (account_id, actor_type, actor_id, action,
                        resource_type, resource_id, metadata)
SELECT
  account_id,
  'system',
  'ledger-correction',
  'llm_cost_log.correction.delete',
  'scan',
  'c1f854e5-a7b7-463f-942e-057c2e950266',
  jsonb_build_object(
    'reason',       'aborted re-parse attempt; debugging artifact, not scan work',
    'row_ids',      jsonb_agg(id ORDER BY id),
    'rows_removed', count(*),
    'cost_usd_removed', sum(cost_usd),
    'window_start', min(created_at),
    'window_end',   max(created_at),
    'documented_in', 'db/corrections/2026-07-25_remove_reparse_debug_cost_rows.sql'
  )
FROM llm_cost_log
WHERE id BETWEEN 637 AND 642
GROUP BY account_id;

DELETE FROM llm_cost_log WHERE id BETWEEN 637 AND 642;

COMMIT;
