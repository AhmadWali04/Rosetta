"""Worker entrypoint placeholder.

The real worker (background runner for the intake graph, sharing the api
package per AGENTS.md's repo layout) lands in M1. For M0 this is just a
trivial script that docker-compose's `worker` service (built from the api
image/context) can point `command:` at so the service starts cleanly.
"""

from __future__ import annotations


def main() -> None:
    print("worker placeholder — intake graph lands in M1")


if __name__ == "__main__":
    main()
