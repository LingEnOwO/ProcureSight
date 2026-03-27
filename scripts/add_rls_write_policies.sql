-- Migration: add UPDATE and DELETE RLS policies missing from the initial seed.
-- Run this once against your database as the superuser (DATABASE_URL).
--
--   psql $DATABASE_URL -f scripts/add_rls_write_policies.sql

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
