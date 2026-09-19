"""Deterministic scene-snapshot projection.

One canonical snapshot serves the reporting cheat sheet, the ambulance greeter
and the EMS handoff (``docs/sdd.md`` sections 4.2 and 10.1). It is a pure
function of an event set, so replaying the same events in any receipt order
produces the same facts, the same provenance and the same
``snapshotRevision``.

Two fields are deliberately outside that guarantee because they describe
receipt rather than content: ``provenance.receivedAt`` and ``updatedAt`` come
from server receipt time and therefore differ between two ingestion orders.
Neither participates in revision counting.

Precedence is ``confirmed > reported > proposed > unknown``. A weaker fact
never replaces a stronger one; it is retained as a pending proposal so the UI
can offer it for confirmation instead of discarding it. A user correction is a
separate channel: it rewrites the effective detail of the event it references,
so a confirmed field can still be fixed by the person who confirmed it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from . import event_types as et
from .clock import iso, utc
from .errors import RetentionPolicy
from .ingestion import ordered_events
from .models import (
    IncidentRecord,
    JsonDict,
    Provenance,
    ReportedAction,
    SceneSnapshot,
    SnapshotField,
    StoredEvent,
)

FRESH = "fresh"
AGING = "aging"
STALE = "stale"
UNKNOWN_FRESHNESS = "unknown"


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """Age thresholds for labelling a snapshot fact.

    Freshness is computed from the injected clock, never from the wall clock,
    so a projection rendered in a test is reproducible.
    """

    fresh_seconds: float = 60.0
    aging_seconds: float = 300.0

    def classify(self, age_seconds: float | None) -> str:
        if age_seconds is None:
            return UNKNOWN_FRESHNESS
        if age_seconds <= self.fresh_seconds:
            return FRESH
        if age_seconds <= self.aging_seconds:
            return AGING
        return STALE


@dataclass(frozen=True, slots=True)
class EffectiveEvent:
    """An event as it stands after every correction that references it."""

    event: StoredEvent
    detail: JsonDict
    retracted: bool
    correction_event_ids: tuple[str, ...]

    @property
    def observed_at(self) -> datetime:
        raw = self.detail.get("observedAt")
        if isinstance(raw, str):
            try:
                return utc(raw)
            except ValueError:
                pass
        return self.event.envelope.client_time

    @property
    def observed_time_uncertain(self) -> bool:
        if self.detail.get("observedTimeUncertain") is True:
            return True
        return self.event.envelope.client_time_uncertain


def correction_roots(events: Iterable[StoredEvent]) -> dict[str, str]:
    """Map every ``event.corrected`` ID to the original event it ultimately fixes.

    A correction may reference another correction. Following the chain to its
    root means a chain of fixes collapses onto one original, which keeps the
    projection order-invariant.
    """
    targets: dict[str, str] = {}
    for event in events:
        if event.type == et.EVENT_CORRECTED:
            target = event.detail.get("correctsEventId")
            if isinstance(target, str):
                targets[event.event_id] = target

    roots: dict[str, str] = {}
    for event_id in targets:
        seen = {event_id}
        current = targets[event_id]
        while current in targets and current not in seen:
            seen.add(current)
            current = targets[current]
        roots[event_id] = current
    return roots


def resolve_effective_events(
    events: Iterable[StoredEvent],
) -> tuple[EffectiveEvent, ...]:
    """Apply corrections onto their originals, in deterministic order.

    Originals are never modified in the store; this returns the corrected view
    used for projection. The correction events themselves stay in the ordered
    list so the timeline can show both sides of a fix.
    """
    ordered = ordered_events(events)
    roots = correction_roots(ordered)

    patches: dict[str, list[StoredEvent]] = {}
    for event in ordered:
        if event.type != et.EVENT_CORRECTED:
            continue
        root = roots.get(event.event_id)
        if root is not None:
            patches.setdefault(root, []).append(event)

    resolved: list[EffectiveEvent] = []
    for event in ordered:
        if event.type == et.EVENT_CORRECTED:
            resolved.append(EffectiveEvent(event, dict(event.detail), False, ()))
            continue
        detail = dict(event.detail)
        retracted = False
        applied: list[str] = []
        for patch in patches.get(event.event_id, ()):
            applied.append(patch.event_id)
            replacement = patch.detail.get("detail")
            if isinstance(replacement, Mapping):
                detail.update({str(k): v for k, v in replacement.items()})
            if patch.detail.get("retracted") is True:
                retracted = True
            elif patch.detail.get("retracted") is False:
                retracted = False
        resolved.append(EffectiveEvent(event, detail, retracted, tuple(applied)))
    return tuple(resolved)


def _confirmation_for(event: StoredEvent, detail: Mapping[str, Any]) -> str:
    stated = detail.get("confirmation")
    if stated in et.CONFIRMATION_RANK and stated != et.UNKNOWN:
        if event.type == et.OBSERVATION_CONFIRMED:
            return "confirmed"
        # A proposal may not claim confirmation for itself.
        if stated == "confirmed":
            return "reported" if event.envelope.source in et.CONFIRMING_SOURCES else "proposed"
        return stated
    if event.type == et.OBSERVATION_CONFIRMED:
        return "confirmed"
    return "reported" if event.envelope.source in et.CONFIRMING_SOURCES else "proposed"


def _snapshot_revision(events: Iterable[StoredEvent]) -> int:
    """Count append-only events that can change visible snapshot content.

    Observations and reported actions each advance the projection revision.
    Corrections that ultimately target either kind advance it again, including
    retractions and corrections to pending proposals. This stays deterministic
    for the same event set, but unlike recomputing only the final value it never
    reuses a revision when a correction changes existing content.
    """
    materialised = tuple(events)
    content_ids = {
        event.event_id
        for event in materialised
        if event.type
        in (et.OBSERVATION_PROPOSED, et.OBSERVATION_CONFIRMED, et.ACTION_REPORTED)
    }
    roots = correction_roots(materialised)
    correction_count = sum(
        1
        for event in materialised
        if event.type == et.EVENT_CORRECTED and roots.get(event.event_id) in content_ids
    )
    return len(content_ids) + correction_count


def project_scene_snapshot(
    incident: IncidentRecord,
    events: Iterable[StoredEvent],
    *,
    now: datetime,
    policy: FreshnessPolicy | None = None,
    retention: RetentionPolicy | None = None,
    through_sequence: int | None = None,
) -> SceneSnapshot:
    """Project the canonical scene snapshot from an event set.

    ``through_sequence`` bounds the projection to events already received up to
    a server sequence, which is how a lagging projection catches up in steps
    without ever seeing a partial event.
    """
    policy = policy or FreshnessPolicy()
    retention = retention or RetentionPolicy()

    selected = [
        event
        for event in events
        if through_sequence is None or event.server_sequence <= through_sequence
    ]
    effective = resolve_effective_events(selected)

    fields: dict[str, JsonDict] = {}
    pending: dict[str, list[JsonDict]] = {}
    actions: list[JsonDict] = []
    revision = _snapshot_revision(selected)
    boundary_event = max(selected, key=lambda event: event.server_sequence, default=None)
    boundary_event_id = boundary_event.event_id if boundary_event is not None else None
    generated_through_revision = 0
    max_sequence = 0
    latest_server_time: datetime | None = None

    for item in effective:
        event = item.event
        max_sequence = max(max_sequence, event.server_sequence)
        if latest_server_time is None or event.server_time > latest_server_time:
            latest_server_time = event.server_time
        if event.type in (et.INCIDENT_STATE_UPDATED, et.DECISION_COMMITTED):
            asserted = item.detail.get("stateRevision")
            if isinstance(asserted, int) and not isinstance(asserted, bool):
                generated_through_revision = max(generated_through_revision, asserted)

        if item.retracted and event.type != et.ACTION_REPORTED:
            continue

        if event.type in (et.OBSERVATION_PROPOSED, et.OBSERVATION_CONFIRMED):
            _apply_observation(item, fields, pending)
        elif event.type == et.ACTION_REPORTED:
            _apply_action(item, actions)

    sections = _build_sections(fields, pending, now=now, policy=policy)
    reported_actions = tuple(
        ReportedAction(
            action=entry["action"],
            reported_at=utc(entry["reportedAt"]),
            event_id=entry["eventId"],
            source=entry["source"],
            detail=entry["detail"],
            corrected_from_event_ids=tuple(entry["correctedFromEventIds"]),
            retracted=entry["retracted"],
        )
        for entry in actions
    )

    return SceneSnapshot(
        incident_id=incident.incident_id,
        snapshot_revision=revision,
        updated_at=latest_server_time,
        generated_through_revision=generated_through_revision,
        generated_through_sequence=max_sequence,
        generated_through_event_id=boundary_event_id,
        sections=sections,
        actions_performed=reported_actions,
        expires_at=now + timedelta(seconds=retention.projection_seconds),
    )


def _apply_observation(
    item: EffectiveEvent,
    fields: dict[str, JsonDict],
    pending: dict[str, list[JsonDict]],
) -> None:
    event = item.event
    key = item.detail.get("key")
    if key not in et.OBSERVATION_KEYS:
        return

    confirmation = _confirmation_for(event, item.detail)
    value = item.detail.get("value", None)
    evidence = item.detail.get("evidenceEventIds", [])
    evidence_ids = tuple(str(v) for v in evidence) if isinstance(evidence, list) else ()

    candidate: JsonDict = {
        "value": value,
        "source": event.envelope.source,
        "confirmation": confirmation,
        "observedAt": iso(item.observed_at),
        "receivedAt": iso(event.server_time),
        "evidenceEventIds": list(dict.fromkeys((event.event_id, *evidence_ids))),
        "correctionEventIds": list(item.correction_event_ids),
        "observedTimeUncertain": item.observed_time_uncertain,
    }

    current = fields.get(key)
    current_rank = (
        et.CONFIRMATION_RANK[current["confirmation"]] if current else et.CONFIRMATION_RANK[et.UNKNOWN]
    )
    if et.CONFIRMATION_RANK[confirmation] >= current_rank:
        fields[key] = candidate
        return

    # Weaker than what is already held: keep the stronger fact and surface the
    # proposal for explicit confirmation rather than discarding it.
    pending.setdefault(key, []).append(
        {
            "eventId": event.event_id,
            "value": value,
            "source": event.envelope.source,
            "confirmation": confirmation,
            "observedAt": iso(item.observed_at),
        }
    )


def _apply_action(item: EffectiveEvent, actions: list[JsonDict]) -> None:
    event = item.event
    action = item.detail.get("action")
    if not isinstance(action, str) or not action:
        return
    extra = {
        name: value
        for name, value in item.detail.items()
        if name not in {"action", "observedAt", "observedTimeUncertain"}
    }
    actions.append(
        {
            "action": action,
            "reportedAt": iso(item.observed_at),
            "eventId": event.event_id,
            "source": event.envelope.source,
            "detail": extra,
            "correctedFromEventIds": list(item.correction_event_ids),
            "retracted": item.retracted,
        }
    )


def _build_sections(
    fields: Mapping[str, JsonDict],
    pending: Mapping[str, list[JsonDict]],
    *,
    now: datetime,
    policy: FreshnessPolicy,
) -> dict[str, tuple[SnapshotField, ...]]:
    sections: dict[str, tuple[SnapshotField, ...]] = {}
    for section in et.SNAPSHOT_SECTIONS:
        items: list[SnapshotField] = []
        for key in et.SECTION_KEYS[section]:
            entry = fields.get(key)
            proposals = tuple(pending.get(key, ()))
            if entry is None:
                # An unobserved field stays explicitly unknown; it is never
                # rendered as absent or false.
                items.append(
                    SnapshotField(
                        key=key,
                        section=section,
                        value=None,
                        provenance=Provenance("device", et.UNKNOWN, None, None),
                        freshness=UNKNOWN_FRESHNESS,
                        age_seconds=None,
                        pending_proposals=proposals,
                    )
                )
                continue
            observed_at = utc(entry["observedAt"])
            age = (now - observed_at).total_seconds()
            items.append(
                SnapshotField(
                    key=key,
                    section=section,
                    value=entry["value"],
                    provenance=Provenance(
                        source=entry["source"],
                        confirmation=entry["confirmation"],
                        observed_at=observed_at,
                        received_at=utc(entry["receivedAt"]),
                        evidence_event_ids=tuple(entry["evidenceEventIds"]),
                        corrected_from_event_ids=tuple(entry["correctionEventIds"]),
                        observed_time_uncertain=bool(entry["observedTimeUncertain"]),
                    ),
                    freshness=policy.classify(age),
                    age_seconds=age,
                    pending_proposals=proposals,
                )
            )
        sections[section] = tuple(items)
    return sections


__all__ = [
    "AGING",
    "EffectiveEvent",
    "FRESH",
    "FreshnessPolicy",
    "STALE",
    "UNKNOWN_FRESHNESS",
    "correction_roots",
    "project_scene_snapshot",
    "resolve_effective_events",
]
