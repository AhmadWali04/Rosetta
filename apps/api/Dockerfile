# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Install uv (official static binary copy trick — no pip resolution needed).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first so this layer caches across code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Now copy the rest of the api package: app/ (incl. alembic migrations),
# alembic.ini (so `docker compose exec api uv run alembic ...` finds its
# script_location), and scripts/ (pinecone_init.py, seed.py — not needed by
# the running server, but kept available for exec'ing into the container).
COPY app/ ./app/
COPY alembic.ini ./
COPY scripts/ ./scripts/

EXPOSE 8000

# --no-dev: the dev dependency group (ruff/mypy/pytest) was deliberately
# left out of the image (see --no-dev above); without this flag `uv run`
# would re-resolve and download it at every container start.
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
