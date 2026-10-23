"""Alembic environment for SkillBridge.

The database URL is sourced from app.config.get_settings().database_url in
both offline and online mode — never from alembic.ini or context.config
(AGENTS.md: "Config via pydantic-settings. No hardcoded keys ... in
app/config.py"). target_metadata comes from app.db.models.Base, the single
source of truth for the schema (AGENTS.md invariant 7: Postgres is the
source of truth).
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make `app` importable regardless of cwd. This file lives at
# apps/api/app/db/migrations/env.py, so three parents up is apps/api/.
_API_ROOT = Path(__file__).resolve().parents[3]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata for 'autogenerate' support — see app/db/models.py.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Emits SQL to the script output without a live DB connection. The URL
    still comes from app.config, not from alembic.ini.
    """
    url = get_settings().database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode, against a live DB connection.

    config.get_section(...) seeds any other engine options set in
    alembic.ini (e.g. pool class), then we overwrite sqlalchemy.url with
    the value from app.config so the ini file never has to hold it.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_settings().database_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
