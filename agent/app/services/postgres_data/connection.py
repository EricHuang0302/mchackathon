"""Optional transaction binding for repositories used by a Unit of Work."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

import psycopg


class ConnectionBoundRepository:
    def __init__(self, dsn: str, *, connection: psycopg.Connection | None = None) -> None:
        self.dsn = dsn
        self._bound_connection = connection

    @contextmanager
    def _connection_scope(self) -> Iterator[psycopg.Connection]:
        if self._bound_connection is not None:
            yield self._bound_connection
        else:
            with psycopg.connect(self.dsn) as connection:
                yield connection
