-- 0003_cms_credentials.sql — encrypted-at-rest CMS credentials.
--
-- Stores customer CMS credentials (WordPress app passwords, Webflow tokens, …)
-- for the Execute stage. ENVELOPE ENCRYPTION: each row's secret is encrypted
-- with a fresh per-row data key (DEK, AES-256-GCM); the DEK itself is stored
-- encrypted by the master key (KEK) held in env/secrets manager (key_version
-- allows KEK rotation). Plaintext NEVER touches the database, and API
-- responses never include ciphertext or keys.
--
-- Byte layout of both bytea columns: 12-byte IV || 16-byte GCM tag || data.

CREATE TABLE cms_credentials (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id    uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  cms_type      text NOT NULL,             -- config taxonomy: wordpress, webflow, ...
  name          text NOT NULL,             -- user-facing label, e.g. "Main blog"
  key_version   integer NOT NULL DEFAULT 1,
  encrypted_dek bytea NOT NULL,            -- DEK wrapped by the KEK
  ciphertext    bytea NOT NULL,            -- credentials JSON encrypted by the DEK
  status        text NOT NULL DEFAULT 'active',
  last_used_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX cms_credentials_account_name_key ON cms_credentials (account_id, lower(name));
CREATE INDEX cms_credentials_account_id_idx ON cms_credentials (account_id);
CREATE TRIGGER trg_cms_credentials_updated_at BEFORE UPDATE ON cms_credentials
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
