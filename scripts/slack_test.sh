#!/usr/bin/env bash
set -a
source .env.local 2>/dev/null || true
set +a

: "${SLACK_WEBHOOK_URL:?SLACK_WEBHOOK_URL not set in .env.local}"

curl -X POST -H "Content-type: application/json" \
  --data '{"text":"✅ ProcureSight webhook test via script"}' \
  "$SLACK_WEBHOOK_URL"