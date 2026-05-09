import os, psycopg
from dotenv import load_dotenv

load_dotenv(".env.local")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight")
ddl = """
-- Enable pgcrypto for UUID generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- === Base entities ===
-- Organizations
CREATE TABLE IF NOT EXISTS orgs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Users
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL,
  nextauth_user_id TEXT UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Comment for NextAuth linkage
COMMENT ON COLUMN public.users.nextauth_user_id IS
  'Links to nextauth.users.id for authentication identity. Populated on first login.';

-- Vendors
CREATE TABLE IF NOT EXISTS vendors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, name)
);

-- === Ingestion metadata ===
CREATE TABLE IF NOT EXISTS raw_docs (
  id BIGSERIAL PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  s3_key TEXT NOT NULL,
  filename TEXT NOT NULL,
  mime TEXT,
  bytes BIGINT,
  sha256 CHAR(64) NOT NULL,
  uploaded_by UUID REFERENCES users(id) ON DELETE SET NULL,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT raw_docs_sha256_hex CHECK (sha256 ~ '^[0-9a-f]{64}$')
);

-- Uniqueness-per-org to prevent re-uploading the same file
CREATE UNIQUE INDEX IF NOT EXISTS raw_docs_org_sha256_uidx
  ON raw_docs (org_id, sha256);

-- Extractions (structured results from a raw_doc)
CREATE TABLE IF NOT EXISTS extractions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_doc_id BIGINT NOT NULL REFERENCES raw_docs(id) ON DELETE CASCADE,
  invoice_id UUID,
  status TEXT NOT NULL,
  confidence NUMERIC(5,2),
  needs_review BOOLEAN NOT NULL DEFAULT false,
  payload_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- === Core accounting objects ===
-- Invoices
CREATE TABLE IF NOT EXISTS invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  vendor_id UUID NOT NULL REFERENCES vendors(id),
  raw_doc_id BIGINT REFERENCES raw_docs(id) ON DELETE SET NULL,
  invoice_no TEXT NOT NULL,
  invoice_date DATE,
  due_date DATE,
  currency TEXT,
  subtotal NUMERIC(18,2),
  tax NUMERIC(18,2),
  total NUMERIC(18,2),
  status TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, vendor_id, invoice_no)
);

-- FK from extractions → invoices (defined here because extractions is created before invoices)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'extractions_invoice_id_fkey'
  ) THEN
    ALTER TABLE extractions
      ADD CONSTRAINT extractions_invoice_id_fkey
      FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE SET NULL;
  END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_extractions_invoice_id
  ON extractions (invoice_id);
CREATE INDEX IF NOT EXISTS idx_extractions_needs_review
  ON extractions (needs_review) WHERE needs_review = TRUE;

-- Invoice line items
CREATE TABLE IF NOT EXISTS invoice_lines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  sku TEXT,
  "desc" TEXT,
  qty NUMERIC(18,4),
  unit_price NUMERIC(18,4),
  line_total NUMERIC(18,2)
);

-- === Analytics views ===
-- Per-vendor unit price statistics per SKU/description
CREATE OR REPLACE VIEW vendor_unit_price_stats AS
SELECT
  i.org_id,
  i.vendor_id,
  il.sku,
  il."desc",
  COUNT(*) AS sample_size,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY il.unit_price) AS median_unit_price,
  AVG(il.unit_price) AS mean_unit_price
FROM invoices i
JOIN invoice_lines il ON il.invoice_id = i.id
WHERE il.unit_price IS NOT NULL
GROUP BY i.org_id, i.vendor_id, il.sku, il."desc";

-- Per-vendor historical spend and invoice counts over recent windows
CREATE OR REPLACE VIEW vendor_spend_stats AS
SELECT
  org_id,
  vendor_id,
  -- Last 30 days
  COUNT(*) FILTER (WHERE invoice_date >= current_date - INTERVAL '30 days') AS invoice_count_30d,
  COALESCE(SUM(total) FILTER (WHERE invoice_date >= current_date - INTERVAL '30 days'), 0) AS total_spend_30d,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY total) FILTER (WHERE invoice_date >= current_date - INTERVAL '30 days') AS median_invoice_total_30d,
  -- Last 90 days
  COUNT(*) FILTER (WHERE invoice_date >= current_date - INTERVAL '90 days') AS invoice_count_90d,
  COALESCE(SUM(total) FILTER (WHERE invoice_date >= current_date - INTERVAL '90 days'), 0) AS total_spend_90d,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY total) FILTER (WHERE invoice_date >= current_date - INTERVAL '90 days') AS median_invoice_total_90d
FROM invoices
GROUP BY org_id, vendor_id;


-- === Contracts & policies ===
CREATE TABLE IF NOT EXISTS vendor_contracts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  vendor_id UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  spending_limit NUMERIC(18,2),        -- NULL = no limit enforced
  approved_categories TEXT[],          -- NULL = all categories allowed; matched against line desc/sku
  payment_terms_days INTEGER,          -- NULL = not enforced; max days between invoice_date and due_date
  effective_date DATE,
  expiry_date DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, vendor_id)
);

-- === Alerts & auditing ===
-- Alerts (anomalies, warnings)
CREATE TABLE IF NOT EXISTS alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  vendor_id UUID REFERENCES vendors(id) ON DELETE SET NULL,
  invoice_id UUID REFERENCES invoices(id) ON DELETE SET NULL,
  type TEXT NOT NULL,
  severity TEXT,
  message TEXT,
  meta_json JSONB,
  acknowledged_at TIMESTAMPTZ,
  acknowledged_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved BOOLEAN NOT NULL DEFAULT FALSE
);

-- Partial index for quick unread counts by severity
CREATE INDEX IF NOT EXISTS idx_alerts_severity_unresolved
  ON alerts (severity)
  WHERE resolved = FALSE;

-- Index for unresolved alerts per org ordered by recency
CREATE INDEX IF NOT EXISTS idx_alerts_org_created_unresolved
  ON alerts (org_id, created_at DESC)
  WHERE resolved = FALSE;

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  target TEXT,
  meta_json JSONB,
  at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- === Row Level Security (RLS) scaffolding ===
-- Enable RLS on org-scoped tables
ALTER TABLE users             ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendors           ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_docs          ENABLE ROW LEVEL SECURITY;
ALTER TABLE extractions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices          ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_lines     ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_contracts  ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts            ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log         ENABLE ROW LEVEL SECURITY;

-- Basic org containment policies (use app.org_id GUC; safe no-op if not set)
DO $body$
BEGIN
  -- Users
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'users' AND policyname = 'org_select_users'
  ) THEN
    EXECUTE 'CREATE POLICY org_select_users ON users FOR SELECT USING (org_id = current_setting(''app.org_id'', true)::uuid)';
    EXECUTE 'CREATE POLICY org_insert_users ON users FOR INSERT WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;

  -- Vendors
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'vendors' AND policyname = 'org_select_vendors'
  ) THEN
    EXECUTE 'CREATE POLICY org_select_vendors ON vendors FOR SELECT USING (org_id = current_setting(''app.org_id'', true)::uuid)';
    EXECUTE 'CREATE POLICY org_insert_vendors ON vendors FOR INSERT WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;

  -- Vendor contracts
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'vendor_contracts' AND policyname = 'org_select_vendor_contracts'
  ) THEN
    EXECUTE 'CREATE POLICY org_select_vendor_contracts ON vendor_contracts FOR SELECT USING (org_id = current_setting(''app.org_id'', true)::uuid)';
    EXECUTE 'CREATE POLICY org_insert_vendor_contracts ON vendor_contracts FOR INSERT WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
    EXECUTE 'CREATE POLICY org_update_vendor_contracts ON vendor_contracts FOR UPDATE USING (org_id = current_setting(''app.org_id'', true)::uuid) WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;

  -- Raw docs
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'raw_docs' AND policyname = 'org_select_raw_docs'
  ) THEN
    EXECUTE 'CREATE POLICY org_select_raw_docs ON raw_docs FOR SELECT USING (org_id = current_setting(''app.org_id'', true)::uuid)';
    EXECUTE 'CREATE POLICY org_insert_raw_docs ON raw_docs FOR INSERT WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;

  -- Extractions (join via raw_docs)
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'extractions' AND policyname = 'org_select_extractions'
  ) THEN
    EXECUTE 'CREATE POLICY org_select_extractions ON extractions FOR SELECT USING (EXISTS (SELECT 1 FROM raw_docs rd WHERE rd.id = extractions.raw_doc_id AND rd.org_id = current_setting(''app.org_id'', true)::uuid))';
    EXECUTE 'CREATE POLICY org_insert_extractions ON extractions FOR INSERT WITH CHECK (EXISTS (SELECT 1 FROM raw_docs rd WHERE rd.id = extractions.raw_doc_id AND rd.org_id = current_setting(''app.org_id'', true)::uuid))';
  END IF;

  -- Invoices
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'invoices' AND policyname = 'org_select_invoices'
  ) THEN
    EXECUTE 'CREATE POLICY org_select_invoices ON invoices FOR SELECT USING (org_id = current_setting(''app.org_id'', true)::uuid)';
    EXECUTE 'CREATE POLICY org_insert_invoices ON invoices FOR INSERT WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;

  -- Invoice lines (join via invoices)
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'invoice_lines' AND policyname = 'org_select_invoice_lines'
  ) THEN
    EXECUTE 'CREATE POLICY org_select_invoice_lines ON invoice_lines FOR SELECT USING (EXISTS (SELECT 1 FROM invoices i WHERE i.id = invoice_lines.invoice_id AND i.org_id = current_setting(''app.org_id'', true)::uuid))';
    EXECUTE 'CREATE POLICY org_insert_invoice_lines ON invoice_lines FOR INSERT WITH CHECK (EXISTS (SELECT 1 FROM invoices i WHERE i.id = invoice_lines.invoice_id AND i.org_id = current_setting(''app.org_id'', true)::uuid))';
  END IF;

  -- Alerts
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'alerts' AND policyname = 'org_select_alerts'
  ) THEN
    EXECUTE 'CREATE POLICY org_select_alerts ON alerts FOR SELECT USING (org_id = current_setting(''app.org_id'', true)::uuid)';
    EXECUTE 'CREATE POLICY org_insert_alerts ON alerts FOR INSERT WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;

  -- Audit log
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'audit_log' AND policyname = 'org_select_audit_log'
  ) THEN
    EXECUTE 'CREATE POLICY org_select_audit_log ON audit_log FOR SELECT USING (org_id = current_setting(''app.org_id'', true)::uuid)';
    EXECUTE 'CREATE POLICY org_insert_audit_log ON audit_log FOR INSERT WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;
END;
$body$;

-- === App role for FastAPI (non-superuser so RLS is enforced) ===
-- The 'procure' superuser bypasses RLS; app_user respects all policies.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user LOGIN PASSWORD 'app_password';
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON vendor_contracts TO app_user;
"""
with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        # Apply DDL
        cur.execute(ddl)
        conn.commit()

        # 1) Demo Org
        cur.execute(
            "INSERT INTO orgs (name) VALUES (%s) "
            "ON CONFLICT (name) DO NOTHING RETURNING id",
            ("Demo Org",),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT id FROM orgs WHERE name=%s", ("Demo Org",))
            row = cur.fetchone()
        demo_org_id = row[0]

        # 2) Demo Uploader user
        cur.execute(
            "INSERT INTO users (org_id, email, role) VALUES (%s, %s, %s) "
            "ON CONFLICT (email) DO NOTHING RETURNING id",
            (demo_org_id, "uploader@demo.local", "admin"),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT id FROM users WHERE email=%s", ("uploader@demo.local",))
            row = cur.fetchone()
        demo_user_id = row[0]

        # === NextAuth tables (frontend authentication) ===
        # These tables are used by apps/web for NextAuth.js authentication
        # They are separate from business logic tables above
        print("Creating NextAuth tables...")
        nextauth_sql_path = os.path.join(os.path.dirname(__file__), "nextauth_tables.sql")
        with open(nextauth_sql_path, "r") as f:
            nextauth_ddl = f.read()
        cur.execute(nextauth_ddl)

        # === RLS write policies (UPDATE / DELETE) ===
        # Supplements the SELECT/INSERT policies created above.
        cur.execute("""
DO $body$
BEGIN

  -- vendors: UPDATE (needed by ON CONFLICT DO UPDATE in ensure_vendor)
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'vendors' AND policyname = 'org_update_vendors'
  ) THEN
    EXECUTE 'CREATE POLICY org_update_vendors ON vendors FOR UPDATE
      USING      (org_id = current_setting(''app.org_id'', true)::uuid)
      WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;

  -- invoices: UPDATE (needed by ON CONFLICT DO UPDATE in upsert_invoice)
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'invoices' AND policyname = 'org_update_invoices'
  ) THEN
    EXECUTE 'CREATE POLICY org_update_invoices ON invoices FOR UPDATE
      USING      (org_id = current_setting(''app.org_id'', true)::uuid)
      WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;

  -- invoice_lines: DELETE (needed by replace_lines)
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'invoice_lines' AND policyname = 'org_delete_invoice_lines'
  ) THEN
    EXECUTE 'CREATE POLICY org_delete_invoice_lines ON invoice_lines FOR DELETE
      USING (EXISTS (
        SELECT 1 FROM invoices i
        WHERE i.id = invoice_lines.invoice_id
          AND i.org_id = current_setting(''app.org_id'', true)::uuid
      ))';
  END IF;

  -- alerts: UPDATE (needed by update_alert_status)
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'alerts' AND policyname = 'org_update_alerts'
  ) THEN
    EXECUTE 'CREATE POLICY org_update_alerts ON alerts FOR UPDATE
      USING      (org_id = current_setting(''app.org_id'', true)::uuid)
      WITH CHECK (org_id = current_setting(''app.org_id'', true)::uuid)';
  END IF;

END;
$body$;
        """)

        conn.commit()

        print("v0 schema created")
        print(f"DEMO_ORG_ID={demo_org_id}")
        print(f"DEMO_UPLOADER_ID={demo_user_id}")
