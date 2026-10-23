.PHONY: up up-offline down migrate pinecone-init seed reindex vector-audit \
        test-api test-web lint gen-client eval eval-fast

# --- M0: real targets -------------------------------------------------

up:
	docker compose up --build

up-offline:
	VECTOR_BACKEND=pinecone-local docker compose --profile offline up --build

down:
	docker compose down

migrate:
	docker compose exec api uv run alembic upgrade head

pinecone-init:
	cd apps/api && uv run python scripts/pinecone_init.py

seed:
	cd apps/api && uv run python -m scripts.seed

reindex:
	@echo "make reindex is a stretch target not required for M0 acceptance;"
	@echo "use 'make vector-audit NS=<namespace>' to check parity, then re-run"
	@echo "'make seed' (JD + taxonomy) to rebuild those two namespaces."

vector-audit:
	@echo "NOTE: M0 wiring only — expected_ids isn't pulled from Postgres yet,"
	@echo "so 'orphaned' below lists everything Pinecone holds for this namespace."
	cd apps/api && uv run python -c "\
	import asyncio; \
	from app.rag.indexer import audit_namespace; \
	print(asyncio.run(audit_namespace('$(NS)', [])))"

test-api:
	cd apps/api && uv run pytest tests/ -v

lint:
	cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run mypy

# --- Deferred past M0 (stub targets) -----------------------------------

gen-client:
	@echo "not implemented until M1/M2 (needs an OpenAPI-emitting API)"

test-web:
	@echo "not implemented until M1 (apps/web has no tests yet)"

eval:
	@echo "not implemented until M5 (eval harness)"

eval-fast:
	@echo "not implemented until M5 (eval harness)"
