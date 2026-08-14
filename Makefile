.PHONY: up down ps logs dbshell seed openapi types slack-test mailhog scoring-corpus

up:        ## start db + minio + redis + mailhog and init minio bucket
	docker compose up -d db minio redis mailhog minio-init

worker:    ## run ARQ worker (requires Redis at localhost:6379)
	arq apps.api.worker.settings.WorkerSettings

down:      ## stop all
	docker compose down -v

ps:
	docker compose ps

dbshell:   ## psql into DB from host
	psql "postgresql://procure:procure@localhost:5432/procuresight"

seed:      ## create tables/fixtures
	python scripts/seed.py

openapi:   ## dump OpenAPI spec to openapi.json
	python -m apps.api.generate_openapi

types: openapi  ## generate TS types from openapi.json
	pnpm dlx openapi-typescript openapi.json -o packages/types/api.d.ts

scoring-corpus:  ## recapture the scoring golden corpus — see dataset/golden/README.md first
	python -m scripts.scoring_corpus.capture

slack-test:
	./scripts/slack_test.sh
