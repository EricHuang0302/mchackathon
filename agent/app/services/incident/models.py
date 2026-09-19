"""Domain records for the incident event store and its projections.

All records are frozen dataclasses. Nothing here mutates an accepted event:
history is append-only, and a correction is a new event that references the
original (``docs/sdd.md`` sections 4.2 and 10.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Mapping

from . import event_types as et
from .clock import iso

JsonDict = dict[str, Any]


def _freeze(value: Any) -> Any:
    """Deep-copy a JSON-shaped value so a caller cannot mutate stored history."""
    if isinstance(value, Mapping):
        return {str(key): _freeze(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_freeze(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """A validated client-submitted event.

    ``client_time`` is the occurrence / client time and ``client_sequence`` the
    client's local order. Neither is trusted as a server timestamp; the server
    records its own receipt time separately on :class:`StoredEvent`.
    """

    event_id: str
    type: str
    detail: JsonDict
    client_id: str
    client_instance_id: str
    client_sequence: int
    client_time: datetime
    authority_epoch: int
    state_revision: int
    mode_revision: int
    rule_version: str
    source: str
    client_time_uncertain: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "detail", _freeze(self.detail))


@dataclass(frozen=True, slots=True)
class StoredEvent:
    """An appended event: the client envelope plus server-assigned facts."""

    incident_id: str
    envelope: EventEnvelope
    actor_id: str
    actor_role: str
    server_time: datetime
    server_sequence: int
    expires_at: datetime

    @property
    def event_id(self) -> str:
        return self.envelope.event_id

    @property
    def type(self) -> str:
        return self.envelope.type

    @property
    def detail(self) -> JsonDict:
        return self.envelope.detail

    @property
    def order_key(self) -> tuple[datetime, str, int, str]:
        """Deterministic total order over events.

        Ordered by client occurrence time first, because server receipt time
        must not reorder events that happened while a client was offline
        (section 7.4). ``client_id`` then ``client_sequence`` break ties across
        and within clients; ``event_id`` makes the order total even for two
        events a client stamped identically.
        """
        return (
            self.envelope.client_time,
            self.envelope.client_id,
            self.envelope.client_sequence,
            self.envelope.event_id,
        )

    def to_dict(self) -> JsonDict:
        envelope = self.envelope
        return {
            "eventId": envelope.event_id,
            "type": envelope.type,
            "detail": _freeze(envelope.detail),
            "source": envelope.source,
            "actorId": self.actor_id,
            "actorRole": self.actor_role,
            "clientId": envelope.client_id,
            "clientInstanceId": envelope.client_instance_id,
            "clientSequence": envelope.client_sequence,
            "clientTime": iso(envelope.client_time),
            "clientTimeUncertain": envelope.client_time_uncertain,
            "serverTime": iso(self.server_time),
            "serverSequence": self.server_sequence,
            "authorityEpoch": envelope.authority_epoch,
            "stateRevision": envelope.state_revision,
            "modeRevision": envelope.mode_revision,
            "ruleVersion": envelope.rule_version,
            "expiresAt": iso(self.expires_at),
        }


@dataclass(frozen=True, slots=True)
class Acknowledgement:
    """Result for one event in a batch.

    ``status`` is ``accepted`` for a newly appended event and ``duplicate`` for
    a retried one. A duplicate returns the original acknowledgement verbatim,
    so a retried batch is indistinguishable from the first attempt.
    """

    event_id: str
    status: str
    server_time: datetime
    server_sequence: int
    client_sequence: int
    client_id: str

    def to_dict(self) -> JsonDict:
        return {
            "eventId": self.event_id,
            "status": self.status,
            "serverTime": iso(self.server_time),
            "serverSequence": self.server_sequence,
            "clientSequence": self.client_sequence,
            "clientId": self.client_id,
        }


@dataclass(frozen=True, slots=True)
class EventConflict:
    """A rejected event. The rest of the batch is still processed."""

    event_id: str | None
    code: str
    reason: str
    detail: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "eventId": self.event_id,
            "code": self.code,
            "reason": self.reason,
            "detail": _freeze(self.detail),
        }


@dataclass(frozen=True, slots=True)
class IncidentRecord:
    """Canonical incident state.

    ``interaction_mode`` is deliberately independent of ``clinical_state``,
    connection state and ``status`` (section 5).
    """

    incident_id: str
    owner_uid: str
    primary_client_id: str
    rule_version: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    status: str = "active"
    interaction_mode: str = "call_119"
    mode_revision: int = 0
    clinical_state: str | None = None
    guidance_paused: bool = False
    state_revision: int = 0
    authority_epoch: int = 0
    call_status: JsonDict = field(default_factory=dict)
    acknowledged_client_sequences: Mapping[str, int] = field(default_factory=dict)

    def last_acknowledged_client_sequence(self, client_id: str) -> int:
        return int(self.acknowledged_client_sequences.get(client_id, 0))

    def to_dict(self) -> JsonDict:
        return {
            "incidentId": self.incident_id,
            "ownerUid": self.owner_uid,
            "primaryClientId": self.primary_client_id,
            "ruleVersion": self.rule_version,
            "status": self.status,
            "interactionMode": self.interaction_mode,
            "modeRevision": self.mode_revision,
            "clinicalState": self.clinical_state,
            "guidancePaused": self.guidance_paused,
            "stateRevision": self.state_revision,
            "authorityEpoch": self.authority_epoch,
            "callStatus": _freeze(self.call_status),
            "createdAt": iso(self.created_at),
            "updatedAt": iso(self.updated_at),
            "expiresAt": iso(self.expires_at),
            "lastAcknowledgedClientSequence": {
                client: int(value)
                for client, value in sorted(self.acknowledged_client_sequences.items())
            },
        }


@dataclass(frozen=True, slots=True)
class EventBatchResult:
    """Outcome of one bounded ordered event batch."""

    incident: IncidentRecord
    acknowledgements: tuple[Acknowledgement, ...] = ()
    conflicts: tuple[EventConflict, ...] = ()

    @property
    def accepted(self) -> tuple[Acknowledgement, ...]:
        return tuple(a for a in self.acknowledgements if a.status == "accepted")

    @property
    def duplicates(self) -> tuple[Acknowledgement, ...]:
        return tuple(a for a in self.acknowledgements if a.status == "duplicate")

    def to_dict(self) -> JsonDict:
        return {
            "acknowledgements": [a.to_dict() for a in self.acknowledgements],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "incident": self.incident.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a snapshot field came from and how strongly it is held."""

    source: str
    confirmation: str
    observed_at: datetime | None
    received_at: datetime | None
    evidence_event_ids: tuple[str, ...] = ()
    corrected_from_event_ids: tuple[str, ...] = ()
    observed_time_uncertain: bool = False

    def to_dict(self) -> JsonDict:
        return {
            "source": self.source,
            "confirmation": self.confirmation,
            "observedAt": iso(self.observed_at) if self.observed_at else None,
            "receivedAt": iso(self.received_at) if self.received_at else None,
            "evidenceEventIds": list(self.evidence_event_ids),
            "correctedFromEventIds": list(self.corrected_from_event_ids),
            "observedTimeUncertain": self.observed_time_uncertain,
        }


def unknown_provenance() -> Provenance:
    return Provenance("device", et.UNKNOWN, None, None)


@dataclass(frozen=True, slots=True)
class SnapshotField:
    """One scene-snapshot fact with provenance, freshness and pending proposals.

    An unknown field is still present, with ``value`` ``None`` and
    ``confirmation`` ``"unknown"``. Absence is never rendered as ``False``.
    """

    key: str
    section: str
    value: Any = None
    provenance: Provenance = field(default_factory=unknown_provenance)
    freshness: str = "unknown"
    age_seconds: float | None = None
    pending_proposals: tuple[JsonDict, ...] = ()

    @property
    def is_unknown(self) -> bool:
        return self.provenance.confirmation == et.UNKNOWN

    def to_dict(self) -> JsonDict:
        return {
            "key": self.key,
            "section": self.section,
            "value": _freeze(self.value),
            "provenance": self.provenance.to_dict(),
            "freshness": self.freshness,
            "ageSeconds": self.age_seconds,
            "pendingProposals": [_freeze(p) for p in self.pending_proposals],
        }


@dataclass(frozen=True, slots=True)
class ReportedAction:
    """A user- or helper-reported action.

    A report is never derived from a recommendation or an issued command: a
    button tap states that something was done, an instruction does not.
    """

    action: str
    reported_at: datetime
    event_id: str
    source: str
    detail: JsonDict = field(default_factory=dict)
    corrected_from_event_ids: tuple[str, ...] = ()
    retracted: bool = False

    def to_dict(self) -> JsonDict:
        return {
            "action": self.action,
            "reportedAt": iso(self.reported_at),
            "eventId": self.event_id,
            "source": self.source,
            "detail": _freeze(self.detail),
            "correctedFromEventIds": list(self.corrected_from_event_ids),
            "retracted": self.retracted,
        }


@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    """The one canonical user-facing scene snapshot.

    ``snapshot_revision`` versions the projection itself.
    ``generated_through_*`` records the event boundary the projection covers.
    They are distinct: replaying the same boundary must not bump the revision.
    """

    incident_id: str
    snapshot_revision: int
    updated_at: datetime | None
    generated_through_revision: int
    generated_through_sequence: int
    generated_through_event_id: str | None
    sections: Mapping[str, tuple[SnapshotField, ...]]
    actions_performed: tuple[ReportedAction, ...] = ()
    expires_at: datetime | None = None

    def field_for(self, key: str) -> SnapshotField:
        section = et.OBSERVATION_KEYS[key]
        for item in self.sections[section]:
            if item.key == key:
                return item
        raise KeyError(key)

    def to_dict(self) -> JsonDict:
        return {
            "incidentId": self.incident_id,
            "snapshotRevision": self.snapshot_revision,
            "updatedAt": iso(self.updated_at) if self.updated_at else None,
            "generatedThroughRevision": self.generated_through_revision,
            "generatedThroughSequence": self.generated_through_sequence,
            "generatedThroughEventId": self.generated_through_event_id,
            "expiresAt": iso(self.expires_at) if self.expires_at else None,
            "sections": {
                name: [item.to_dict() for item in self.sections[name]]
                for name in et.SNAPSHOT_SECTIONS
            },
            "actionsPerformed": [a.to_dict() for a in self.actions_performed],
        }


@dataclass(frozen=True, slots=True)
class MistEntry:
    """One MIST line, always carrying the events that justify it."""

    key: str
    value: Any
    confirmation: str
    observed_at: datetime | None
    evidence_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        return {
            "key": self.key,
            "value": _freeze(self.value),
            "confirmation": self.confirmation,
            "observedAt": iso(self.observed_at) if self.observed_at else None,
            "evidenceEventIds": list(self.evidence_event_ids),
        }


@dataclass(frozen=True, slots=True)
class MistReport:
    """Mechanism / Injuries / Signs / Treatment.

    The four treatment lists stay separate on purpose: a recommendation, an
    issued command, a device acknowledgement and a reported action are four
    different claims and must never be merged into "treatment given".
    """

    incident_id: str
    snapshot_revision: int
    generated_through_revision: int
    generated_through_sequence: int
    mechanism: tuple[MistEntry, ...] = ()
    injuries: tuple[MistEntry, ...] = ()
    signs: tuple[MistEntry, ...] = ()
    reported_actions: tuple[ReportedAction, ...] = ()
    recommended_actions: tuple[JsonDict, ...] = ()
    issued_commands: tuple[JsonDict, ...] = ()
    device_acknowledgements: tuple[JsonDict, ...] = ()

    def to_dict(self) -> JsonDict:
        return {
            "incidentId": self.incident_id,
            "snapshotRevision": self.snapshot_revision,
            "generatedThroughRevision": self.generated_through_revision,
            "generatedThroughSequence": self.generated_through_sequence,
            "mechanism": [e.to_dict() for e in self.mechanism],
            "injuries": [e.to_dict() for e in self.injuries],
            "signs": [e.to_dict() for e in self.signs],
            "treatment": {
                "reportedActions": [a.to_dict() for a in self.reported_actions],
                "recommendedActions": [_freeze(a) for a in self.recommended_actions],
                "issuedCommands": [_freeze(c) for c in self.issued_commands],
                "deviceAcknowledgements": [
                    _freeze(a) for a in self.device_acknowledgements
                ],
            },
        }


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """A sanitized timeline row. Fields are allowlisted per viewer role."""

    event_id: str
    type: str
    server_sequence: int
    client_time: datetime
    server_time: datetime
    detail: JsonDict
    source: str
    actor_role: str
    corrects_event_id: str | None = None
    corrected_by_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        return {
            "eventId": self.event_id,
            "type": self.type,
            "serverSequence": self.server_sequence,
            "clientTime": iso(self.client_time),
            "serverTime": iso(self.server_time),
            "detail": _freeze(self.detail),
            "source": self.source,
            "actorRole": self.actor_role,
            "correctsEventId": self.corrects_event_id,
            "correctedByEventIds": list(self.corrected_by_event_ids),
        }


@dataclass(frozen=True, slots=True)
class TimelinePage:
    """A bounded page of the handoff timeline."""

    entries: tuple[TimelineEntry, ...]
    next_cursor: str | None
    has_more: bool
    page_size: int
    generated_through_sequence: int
    viewer_role: str

    def to_dict(self) -> JsonDict:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "nextCursor": self.next_cursor,
            "hasMore": self.has_more,
            "pageSize": self.page_size,
            "generatedThroughSequence": self.generated_through_sequence,
            "viewerRole": self.viewer_role,
        }


def with_updated(record: IncidentRecord, **changes: Any) -> IncidentRecord:
    """Return a copy of ``record`` with ``changes`` applied."""
    return replace(record, **changes)


__all__ = [
    "Acknowledgement",
    "EventBatchResult",
    "EventConflict",
    "EventEnvelope",
    "IncidentRecord",
    "JsonDict",
    "MistEntry",
    "MistReport",
    "Provenance",
    "ReportedAction",
    "SceneSnapshot",
    "SnapshotField",
    "StoredEvent",
    "TimelineEntry",
    "TimelinePage",
    "unknown_provenance",
    "with_updated",
]
