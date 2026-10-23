.PHONY: up up-offline down migrate smoke-hr pinecone-init seed reindex vector-audit \
        test-api test-web lint gen-client eval eval-fast

# --- M0: real targets -------------------------------------------------

up:
	docker compose up --build

up-offline:
	VECTOR_BACKEND=pinecone-local docker compose --profile offline up --build

down:
	docker compose down

migrate:
	docker compose exec api uv run --no-dev alembic upgrade head

# Creates, migrates, verifies and removes its own isolated local Postgres DB.
# Uses fake LLM + memory vectors; never sends data to cloud providers.
smoke-hr:
	cd apps/api && uv run --env-file ../../.env python -m scripts.smoke_hr

# NOTE: these run against the local `uv` env, not inside Docker, so they
# need the root .env explicitly — Settings' default env_file=".env" would
# otherwise resolve relative to apps/api/ (which has no .env of its own)
# since `cd apps/api` changes cwd before uv runs.
pinecone-init:
	cd apps/api && uv run --env-file ../../.env python scripts/pinecone_init.py

seed:
	cd apps/api && uv run --env-file ../../.env python -m scripts.seed

reindex:
	@echo "make reindex is a stretch target not required for M0 acceptance;"
	@echo "use 'make vector-audit NS=<namespace>' to check parity, then re-run"
	@echo "'make seed' (JD + taxonomy) to rebuild those two namespaces."

vector-audit:
	@echo "NOTE: M0 wiring only — expected_ids isn't pulled from Postgres yet,"
	@echo "so 'orphaned' below lists everything Pinecone holds for this namespace."
	cd apps/api && uv run --env-file ../../.env python -c "\
	import asyncio; \
	from app.rag.indexer import audit_namespace; \
	print(asyncio.run(audit_namespace('$(NS)', [])))"

test-api:
	cd apps/api && uv run pytest tests/ -v

lint:
	cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd apps/web && npm run lint && npx --no-install tsc --noEmit

# --- M1: real targets ---------------------------------------------------

gen-client:
	cd apps/api && uv run --no-dev python scripts/emit_openapi.py > ../web/openapi.json
	cd apps/web && npx openapi-typescript openapi.json -o lib/api-types.ts

test-web:
	cd apps/web && npm run test

# --- Deferred past M1 (stub targets) -------------------------------------

eval:
	@echo "not implemented until M5 (eval harness)"

eval-fast:
	@echo "not implemented until M5 (eval harness)"
