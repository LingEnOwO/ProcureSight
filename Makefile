.PHONY: up down ps logs dbshell seed load-samples openapi types

up:        ## start db + minio
	docker compose up -d db minio

down:      ## stop all
	docker compose down -v

ps:
	docker compose ps

dbshell:   ## psql into DB from host
	psql "postgresql://procure:procure@localhost:5432/procuresight"

seed:      ## create tables/fixtures
	python scripts/seed.py

load-samples: ## upload samples to S3 + register rows
	python scripts/load_samples.py data/samples

openapi:   ## dump OpenAPI spec to openapi.json
	python -m apps.api.generate_openapi

types: openapi  ## generate TS types from openapi.json
	pnpm dlx openapi-typescript openapi.json -o packages/types/api.d.ts