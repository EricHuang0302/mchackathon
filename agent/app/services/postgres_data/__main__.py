"""Command-line entry point for schema migration and retention cleanup."""

from __future__ import annotations

import argparse
import json
import os

from .migration import apply_migrations
from .retention import PostgresRetentionService


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.services.postgres_data")
    parser.add_argument("command", choices=("migrate", "cleanup"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    if arguments.command == "migrate":
        applied = apply_migrations(arguments.database_url)
        print(json.dumps({"appliedMigrations": list(applied)}, sort_keys=True))
    else:
        result = PostgresRetentionService(
            arguments.database_url,
            legacy_invite_key=os.getenv("LOCAL_INVITE_KEY"),
        ).purge()
        print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
