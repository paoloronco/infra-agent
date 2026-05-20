"""Alembic environment — uses the same engine as db.py."""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# Ensure the backend package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from db import engine, Base
import models_db  # noqa — registers all ORM models with Base.metadata

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # render_as_batch=True is required for SQLite: it recreates tables
            # for column-level changes that SQLite's ALTER TABLE doesn't support.
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
