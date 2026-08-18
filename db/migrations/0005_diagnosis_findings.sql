-- ---------------------------------------------------------------------------
-- 0005_diagnosis_findings — persist what the checks actually observed.
--
-- Diagnosis produced ~7 findings per scan and stored the NUMBER 7. Gaps survived;
-- everything else — including every check that concluded "no problem here" — was
-- discarded at the end of the run. Two consequences, both bad:
--
--   * a correct verdict was exactly as unauditable as a wrong one. When the
--     sitemap-based comparison check stopped raising a false gap for imagine.art,
--     nothing in the record could show WHY: not the sitemap it read, not the URLs
--     it matched, not whether it fell back to the homepage heuristic.
--   * passes were invisible. "We checked and it's fine" is a product claim, and
--     it was backed by nothing a customer or an engineer could re-walk.
--
-- Findings are per-scan facts, not mutable state — this table is append-only in
-- practice; a re-run writes a new scan's rows rather than updating these.
--
-- `detail` carries the check's own audit trail (for the comparison check: the
-- robots.txt Sitemap directives, each sitemap document fetched with its status
-- and <loc> count, how many URLs were read, how many matched the pattern, and a
-- sample of matches). `evidence` carries the fetch records already defined by
-- diagnosis.contracts.Evidence, including the truncation flags from 0004-era work.
-- ---------------------------------------------------------------------------

CREATE TABLE diagnosis_findings (
  id           bigserial PRIMARY KEY,
  account_id   uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  scan_id      uuid REFERENCES scans (id) ON DELETE CASCADE,
  layer        text NOT NULL,
  code         text NOT NULL,
  ok           boolean NOT NULL,
  severity     text NOT NULL,
  summary      text NOT NULL,
  gap_type     text,
  -- confirmed_present | confirmed_absent | check_failed. Deliberately text, not
  -- an enum: the epistemic vocabulary is still settling, and a migration to add a
  -- state would be a poor reason to lose a scan's record.
  status       text NOT NULL,
  confidence   numeric NOT NULL DEFAULT 1.0,
  -- Does the negative verdict rest on NOT finding something? Absence-based
  -- verdicts are the ones a truncated fetch invalidates.
  from_absence boolean NOT NULL DEFAULT true,
  detail       jsonb NOT NULL DEFAULT '{}',
  evidence     jsonb NOT NULL DEFAULT '[]',
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- The two access patterns: "everything this scan observed" and "how has this
-- check behaved over time for this account" (the regression question).
CREATE INDEX diagnosis_findings_scan_idx ON diagnosis_findings (scan_id);
CREATE INDEX diagnosis_findings_account_code_idx
  ON diagnosis_findings (account_id, code, created_at DESC);
