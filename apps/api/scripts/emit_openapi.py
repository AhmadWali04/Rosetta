"""Emits the FastAPI app's OpenAPI schema as JSON on stdout.

Used by `make gen-client` to feed `openapi-typescript` (see Makefile):

    cd apps/api && uv run --no-dev python scripts/emit_openapi.py > ../web/openapi.json

Deliberately does not start a server or touch the database: FastAPI builds
`app.openapi()` purely from route/dependency declarations at import time, so
this only requires `app.main` to import cleanly without a live DB
connection. If a future route performs DB/Pinecone work at *import* time
(rather than inside a request handler/dependency), this script will need to
stub that out — but nothing in `app/main.py` or its routers should do that
per FastAPI convention (dependencies only run per-request).
"""

from __future__ import annotations

import json

from app.main import app

if __name__ == "__main__":
    print(json.dumps(app.openapi()))
