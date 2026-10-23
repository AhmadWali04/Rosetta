"""Read-only parity audit CLI for ``make vector-audit [NS=<namespace>]``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from typing import Any

from app.db.session import session_scope
from app.services.vector_health import audit_vectors


async def _run(namespace: str | None) -> list[dict[str, Any]]:
    with session_scope() as db:
        return await audit_vectors(db, namespace)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit configured vector namespaces against Postgres"
    )
    parser.add_argument(
        "--namespace",
        default=os.environ.get("NS") or None,
        help="Audit one known namespace; default: NS environment variable or all",
    )
    args = parser.parse_args(argv)
    try:
        reports = asyncio.run(_run(args.namespace))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    except Exception as exc:
        # Connection/SDK exception text can contain URLs or credentials.
        print(json.dumps({"error": "Vector audit failed", "type": type(exc).__name__}))
        return 2
    print(json.dumps(reports, indent=2))
    return 0 if all(report["parity"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
