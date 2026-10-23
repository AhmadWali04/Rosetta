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

# Now copy the rest of the api package (app/) and the worker package, since
# the worker service reuses this same image/build context (AGENTS.md repo
# layout: "worker: Background runner for intake graph (shares api package)").
COPY app/ ./app/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
