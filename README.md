cat > README.md <<'EOF'
# ProcureSight

AI-assisted invoice & contract intelligence with anomaly alerts.

## Stack (v0.1)
- Postgres (db) • MinIO (S3-compatible) • Python scripts (seed/load)
- Planned: Next.js (web), FastAPI (api), MailHog (dev email)

## Quickstart
```bash
make up            # start db + minio
make seed          # create schema
make load-samples  # upload to MinIO and insert rows in raw_docs

MinIO console: http://localhost:9001 (minioadmin / minioadmin)