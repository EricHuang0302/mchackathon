"""Reconnect and offline reconciliation.

A returning client uploads its bounded ordered outbox from the last
acknowledged sequence, and receives acknowledgements, conflicts, a reconciled
state and the events it missed (``docs/sdd.md`` section 7.4).

Three invariants drive this module:

* **The local interaction mode wins.** A reconcile never returns a
  ``modeRevision`` lower than the one the client already holds. A server that
  is behind produces a ``stale_revision`` conflict, not a silent downgrade, so
  a reconnect can never unmute an ongoing call.
* **Replay is record-only.** Returned events update local records and
  projections. They must not re-execute treatment prompts, completed commands
  or helper dispatches, which is why
  :attr:`ReconciliationResult.replay_execution_allowed` is always ``False``.
* **Receipt order never reorders occurrence.** Catch-up is paged by server
  sequence, but the projection is built in client-occurrence order, so an
  out-of-order local upload lands in the right place in the snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from . import event_types as et
from .access import ROLE_PRIMARY, Principal
from .clock import Clock
from .errors import INVALID_INPUT, STALE_REVISION, UNAUTHORIZED, ServiceError
from .event_store import EventStore
from .ingestion import IncidentEventService
from .models import (
    Acknowledgement,
    EventConflict,
    EventEnvelope,
    IncidentRecord,
    JsonDict,
    SceneSnapshot,
    StoredEvent,
    with_updated,
)
from .scene_snapshot import FreshnessPolicy, project_scene_snapshot

#: Upper bound on events returned in one catch-up page.
DEFAULT_MAX_REPLAY = 200


@dataclass(frozen=True, slots=True)
class ResyncRequest:
    """What a reconnecting client declares about its own local state."""

    client_id: str
    client_instance_id: str
    interaction_mode: str
    mode_revision: int
    authority_epoch: int
    last_acknowledged_client_sequence: int = 0
    known_server_sequence: int = 0
    events: Sequence[Mapping[str, Any] | EventEnvelope] = ()


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Reconciled state plus everything the client needs to catch up."""

    incident: IncidentRecord
    interaction_mode: str
    mode_revision: int
    authority_epoch: int
    mode_preserved: bool
    resume_from_client_sequence: int
    snapshot: SceneSnapshot
    replay_events: tuple[StoredEvent, ...] = ()
    acknowledgements: tuple[Acknowledgement, ...] = ()
    conflicts: tuple[EventConflict, ...] = ()
    catch_up_complete: bool = True
    #: Replayed history is applied to records and projections only. Executing
    #: it would repeat prompts and commands the incident already performed.
    replay_execution_allowed: bool = field(default=False, init=False)

    @property
    def accepted(self) -> tuple[Acknowledgement, ...]:
        return tuple(a for a in self.acknowledgements if a.status == "accepted")

    @property
    def duplicates(self) -> tuple[Acknowledgement, ...]:
        return tuple(a for a in self.acknowledgements if a.status == "duplicate")

    def to_dict(self) -> JsonDict:
        return {
            "incident": self.incident.to_dict(),
            "interactionMode": self.interaction_mode,
            "modeRevision": self.mode_revision,
            "authorityEpoch": self.authority_epoch,
            "modePreserved": self.mode_preserved,
            "resumeFromClientSequence": self.resume_from_client_sequence,
            "catchUpComplete": self.catch_up_complete,
            "replayExecutionAllowed": self.replay_execution_allowed,
            "acknowledgements": [a.to_dict() for a in self.acknowledgements],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "replayEvents": [e.to_dict() for e in self.replay_events],
            "sceneSnapshot": self.snapshot.to_dict(),
        }


class ReconciliationService:
    """Reconnect handling on top of :class:`IncidentEventService`."""

    def __init__(
        self,
        ingestion: IncidentEventService,
        events: EventStore,
        clock: Clock,
        *,
        max_replay: int = DEFAULT_MAX_REPLAY,
        freshness: FreshnessPolicy | None = None,
    ) -> None:
        self._ingestion = ingestion
        self._events = events
        self._clock = clock
        self._max_replay = max_replay
        self._freshness = freshness or FreshnessPolicy()

    def reconcile(
        self,
        incident_id: str,
        request: ResyncRequest,
        *,
        principal: Principal,
    ) -> ReconciliationResult:
        """Upload an offline branch, then return the reconciled view."""
        incident_before_upload = self._ingestion.get_incident(incident_id)
        if principal.role != ROLE_PRIMARY or principal.incident_id != incident_id:
            raise ServiceError(UNAUTHORIZED, "reconciliation_requires_primary")
        if request.client_id != incident_before_upload.primary_client_id:
            raise ServiceError(
                UNAUTHORIZED,
                "primary_client_mismatch",
                detail={"primaryClientId": incident_before_upload.primary_client_id},
            )
        if principal.client_id is not None and request.client_id != principal.client_id:
            raise ServiceError(UNAUTHORIZED, "principal_client_mismatch")
        if (
            principal.client_instance_id is not None
            and request.client_instance_id != principal.client_instance_id
        ):
            raise ServiceError(UNAUTHORIZED, "principal_client_instance_mismatch")
        if request.interaction_mode not in et.INTERACTION_MODE_SET:
            raise ServiceError(
                INVALID_INPUT,
                "unknown_interaction_mode",
                detail={"interactionMode": request.interaction_mode},
            )

        batch = self._ingestion.ingest_batch(
            incident_id, list(request.events), principal=principal
        )
        incident = batch.incident
        conflicts = list(batch.conflicts)

        incident, epoch_conflict = self._reconcile_epoch(incident, request, principal)
        if epoch_conflict is not None:
            conflicts.append(epoch_conflict)

        mode, mode_revision, mode_conflict = self._reconcile_mode(incident, request)
        if mode_conflict is not None:
            conflicts.append(mode_conflict)

        self._ingestion.save_incident(incident)

        all_events = self._events.list_events(incident_id)
        replay_source = [
            event
            for event in all_events
            if event.server_sequence > request.known_server_sequence
        ]
        replay = tuple(replay_source[: self._max_replay])
        catch_up_complete = len(replay) == len(replay_source)

        now = self._clock.now()
        snapshot = project_scene_snapshot(
            incident, all_events, now=now, policy=self._freshness
        )

        return ReconciliationResult(
            incident=incident,
            interaction_mode=mode,
            mode_revision=mode_revision,
            authority_epoch=incident.authority_epoch,
            mode_preserved=mode == request.interaction_mode,
            resume_from_client_sequence=(
                incident.last_acknowledged_client_sequence(request.client_id) + 1
            ),
            snapshot=snapshot,
            replay_events=replay,
            acknowledgements=batch.acknowledgements,
            conflicts=tuple(conflicts),
            catch_up_complete=catch_up_complete,
        )

    # -- internals ----------------------------------------------------------

    def _reconcile_epoch(
        self,
        incident: IncidentRecord,
        request: ResyncRequest,
        principal: Principal,
    ) -> tuple[IncidentRecord, EventConflict | None]:
        """Adopt the primary runtime's advanced authority epoch.

        A primary that lost its connection advances its own epoch to reject
        commands issued before the outage. The server adopts that epoch so the
        older branch cannot resume issuing commands. Any other caller claiming
        a higher epoch is an ownership conflict.
        """
        if request.authority_epoch <= incident.authority_epoch:
            return incident, None
        if (
            principal.role != ROLE_PRIMARY
            or request.client_id != incident.primary_client_id
        ):
            return incident, EventConflict(
                event_id=None,
                code=UNAUTHORIZED,
                reason="non_primary_authority_epoch_advance",
                detail={"primaryClientId": incident.primary_client_id},
            )
        return with_updated(incident, authority_epoch=request.authority_epoch), None

    def _reconcile_mode(
        self, incident: IncidentRecord, request: ResyncRequest
    ) -> tuple[str, int, EventConflict | None]:
        if request.mode_revision > incident.mode_revision:
            # The browser gate is authoritative. Report the gap instead of
            # handing back an older mode the client would have to ignore.
            return (
                request.interaction_mode,
                request.mode_revision,
                EventConflict(
                    event_id=None,
                    code=STALE_REVISION,
                    reason="server_mode_revision_behind_client",
                    detail={
                        "serverModeRevision": incident.mode_revision,
                        "clientModeRevision": request.mode_revision,
                        "clientInteractionMode": request.interaction_mode,
                    },
                ),
            )
        if request.mode_revision == incident.mode_revision:
            if request.interaction_mode == incident.interaction_mode:
                return incident.interaction_mode, incident.mode_revision, None
            return (
                request.interaction_mode,
                request.mode_revision,
                EventConflict(
                    event_id=None,
                    code=STALE_REVISION,
                    reason="mode_revision_diverged",
                    detail={
                        "serverInteractionMode": incident.interaction_mode,
                        "clientInteractionMode": request.interaction_mode,
                        "modeRevision": request.mode_revision,
                    },
                ),
            )

        # A reconnect must never turn a currently silent/terminal browser gate
        # back into voice guidance. The server state is returned separately in
        # ``incident`` for explicit reconciliation, but the operative mode stays
        # local until the user reports that voice may resume.
        would_unmute = (
            request.interaction_mode in {"call_119", "on_call", "handover"}
            and incident.interaction_mode == "voice_guidance"
        )
        handover_must_stick = (
            request.interaction_mode == "handover"
            and incident.interaction_mode != "handover"
        )
        if would_unmute or handover_must_stick:
            reason = (
                "local_handover_preserved"
                if handover_must_stick
                else "server_mode_would_unsafely_unmute_client"
            )
            return (
                request.interaction_mode,
                request.mode_revision,
                EventConflict(
                    event_id=None,
                    code=STALE_REVISION,
                    reason=reason,
                    detail={
                        "serverModeRevision": incident.mode_revision,
                        "serverInteractionMode": incident.interaction_mode,
                        "clientModeRevision": request.mode_revision,
                        "clientInteractionMode": request.interaction_mode,
                    },
                ),
            )
        return incident.interaction_mode, incident.mode_revision, None


__all__ = [
    "DEFAULT_MAX_REPLAY",
    "ReconciliationResult",
    "ReconciliationService",
    "ResyncRequest",
]
