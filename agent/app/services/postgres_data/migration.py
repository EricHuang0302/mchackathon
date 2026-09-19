"""Apply packaged, forward-only PostgreSQL migrations."""

from __future__ import annotations

from importlib.resources import files

import psycopg

_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS service_schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def apply_migrations(dsn: str) -> tuple[str, ...]:
    """Apply pending migrations transactionally and return their versions."""

    directory = files(__package__).joinpath("migrations")
    migrations = sorted(
        item for item in directory.iterdir() if item.name.endswith(".sql")
    )
    applied: list[str] = []
    with psycopg.connect(dsn) as connection:
        connection.execute(_MIGRATION_TABLE_SQL)
        for migration in migrations:
            version = migration.name.split("_", 1)[0]
            row = connection.execute(
                "SELECT 1 FROM service_schema_migrations WHERE version = %s",
                (version,),
            ).fetchone()
            if row is not None:
                continue
            connection.execute(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO service_schema_migrations (version) VALUES (%s)",
                (version,),
            )
            applied.append(version)
    return tuple(applied)


__all__ = ["apply_migrations"]
