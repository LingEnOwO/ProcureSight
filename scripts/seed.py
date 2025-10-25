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
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Vendors
CREATE TABLE IF NOT EXISTS vendors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, name)
);

-- === Ingestion metadata ===
-- Raw documents (uploaded files)
CREATE TABLE IF NOT EXISTS raw_docs (
  id BIGSERIAL PRIMARY KEY,
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  s3_key TEXT NOT NULL,
  filename TEXT NOT NULL,
  mime TEXT,
  bytes BIGINT,
  uploaded_by UUID REFERENCES users(id) ON DELETE SET NULL,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Compatibility: add org_id to raw_docs if the table pre-existed without it
ALTER TABLE raw_docs
  ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES orgs(id) ON DELETE CASCADE;

-- Extractions (structured results from a raw_doc)
CREATE TABLE IF NOT EXISTS extractions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_doc_id BIGINT NOT NULL REFERENCES raw_docs(id) ON DELETE CASCADE,
  status TEXT NOT NULL,
  confidence NUMERIC(5,2),
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

-- === Alerts & auditing ===
-- Alerts (anomalies, warnings)
CREATE TABLE IF NOT EXISTS alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  invoice_id UUID REFERENCES invoices(id) ON DELETE SET NULL,
  type TEXT NOT NULL,
  severity TEXT,
  message TEXT,
  meta_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved BOOLEAN NOT NULL DEFAULT FALSE
);

-- Partial index for quick unread counts by severity
CREATE INDEX IF NOT EXISTS idx_alerts_severity_unresolved
  ON alerts (severity)
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
ALTER TABLE users         ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendors       ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_docs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE extractions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices      ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log     ENABLE ROW LEVEL SECURITY;

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
"""
with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        # Apply DDL
        cur.execute(ddl)
        conn.commit()

        # --- Bootstrap demo data (idempotent) ---
        # --- Add sha256 column and unique index for idempotent uploads ---
        cur.execute("""
        ALTER TABLE raw_docs
        ADD COLUMN IF NOT EXISTS sha256 CHAR(64);
        """)
        cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS raw_docs_org_sha256_uidx
        ON raw_docs (org_id, sha256);
        """)
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

        conn.commit()

        print("v0 schema created")
        print(f"DEMO_ORG_ID={demo_org_id}")
        print(f"DEMO_UPLOADER_ID={demo_user_id}")
