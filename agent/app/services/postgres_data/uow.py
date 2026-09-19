"""One PostgreSQL transaction for incident events and their projections."""

from __future__ import annotations

import psycopg

from .access import PostgresGrantStore, PostgresInvitationStore
from .incident import PostgresEventStore, PostgresIncidentStore, PostgresSceneSnapshotStore


class PostgresUnitOfWork:
    """Bind repositories to one connection; commit only after all writes succeed."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.connection: psycopg.Connection | None = None

    def __enter__(self) -> PostgresUnitOfWork:
        self.connection = psycopg.connect(self.dsn)
        self.incidents = PostgresIncidentStore(self.dsn, connection=self.connection)
        self.events = PostgresEventStore(self.dsn, connection=self.connection)
        self.snapshots = PostgresSceneSnapshotStore(self.dsn, connection=self.connection)
        self.grants = PostgresGrantStore(self.dsn, connection=self.connection)
        self.invitations = PostgresInvitationStore(self.dsn, connection=self.connection)
        return self

    def lock_incident(self, incident_id: str) -> None:
        if self.connection is None:
            raise RuntimeError("Unit of Work is not active")
        self.connection.execute(
            "SELECT incident_id FROM incidents WHERE incident_id = %s FOR UPDATE",
            (incident_id,),
        )

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.connection is not None:
            self.connection.__exit__(exc_type, exc_value, traceback)
            self.connection = None
