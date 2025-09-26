.PHONY: up down ps logs dbshell seed load-samples

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