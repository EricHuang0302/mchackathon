"""Evidence-backed MIST projection and the sanitized handoff timeline.

MIST is derived only from allowlisted observation keys and from events; no line
is inferred from free text, and every line carries the event IDs that justify
it. A fact nobody reported stays ``unknown`` rather than becoming ``false`` or
being dropped (``docs/sdd.md`` sections 4.3 and 6.2).

The four treatment lists are kept apart on purpose. A rule recommendation, an
issued command, a device acknowledgement and a user-reported action are four
different claims; merging them would let an instruction read as delivered
treatment.

Timeline pages are bounded and cursor-paginated in server receipt order, which
is stable because the event log is append-only. Each entry carries both the
occurrence time and the receipt time so a renderer can order clinically while
paging stably. Detail fields are allowlisted per viewer role, so a field added
to an event type later is withheld from a handoff viewer until it is
explicitly listed here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Iterable, Mapping

from . import event_types as et
from .access import READ_MIST, READ_TIMELINE, ROLE_CAPABILITIES, ROLE_PRIMARY
from .clock import iso
from .errors import INVALID_INPUT, UNAUTHORIZED, ServiceError
from .ingestion import ordered_events
from .models import (
    IncidentRecord,
    JsonDict,
    MistEntry,
    MistReport,
    SceneSnapshot,
    StoredEvent,
    TimelineEntry,
    TimelinePage,
)
from .scene_snapshot import (
    FreshnessPolicy,
    correction_roots,
    project_scene_snapshot,
    resolve_effective_events,
)

DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 200
_CURSOR_PREFIX: Final = "seq:"
_MAX_CURSOR_NUMBER_DIGITS: Final = 19

#: Detail fields a handoff viewer may see, per event type. ``None`` in
#: :data:`ROLE_DETAIL_ALLOWLIST` means the full detail (the primary session).
HANDOFF_DETAIL_ALLOWLIST: Final[dict[str, tuple[str, ...]]] = {
    et.MODE_CHANGED: ("mode", "modeRevision"),
    et.CALL_REPORTED: ("reportedState", "delegatedCallActive"),
    et.ACTION_REPORTED: ("action", "note"),
    et.EVENT_CORRECTED: ("correctsEventId", "reason", "retracted"),
    et.OBSERVATION_PROPOSED: ("key", "value", "confirmation", "observedAt"),
    et.OBSERVATION_CONFIRMED: (
        "key",
        "value",
        "confirmation",
        "observedAt",
        "evidenceEventIds",
    ),
    et.DECISION_COMMITTED: (
        "ruleVersion",
        "fromState",
        "toState",
        "reasonCode",
        "templateId",
        "stateRevision",
    ),
    et.COMMAND_ISSUED: ("commandId", "command", "modeRevision"),
    et.COMMAND_ACKNOWLEDGED: ("commandId", "result"),
    et.TIMER_ELAPSED: ("timerId", "label"),
    # Helper rows carry task progress only. A helper's location history is not
    # part of a clinical handoff.
    et.HELPER_UPDATED: ("helperId", "role", "status"),
    et.INCIDENT_STATE_UPDATED: ("clinicalState", "status", "stateRevision"),
    et.SCENE_SNAPSHOT_UPDATED: ("snapshotRevision", "generatedThroughRevision"),
}

ROLE_DETAIL_ALLOWLIST: Final[dict[str, dict[str, tuple[str, ...]] | None]] = {
    ROLE_PRIMARY: None,
    "ems_viewer": HANDOFF_DETAIL_ALLOWLIST,
}


def _require_capability(viewer_role: str, capability: str) -> None:
    capabilities = ROLE_CAPABILITIES.get(viewer_role)
    if capabilities is None:
        raise ServiceError(
            UNAUTHORIZED, "unknown_viewer_role", detail={"role": viewer_role}
        )
    if capability not in capabilities:
        raise ServiceError(
            UNAUTHORIZED,
            "capability_denied",
            detail={"role": viewer_role, "capability": capability},
        )


def _entry(key: str, snapshot: SceneSnapshot) -> MistEntry:
    field = snapshot.field_for(key)
    return MistEntry(
        key=key,
        value=field.value,
        confirmation=field.provenance.confirmation,
        observed_at=field.provenance.observed_at,
        evidence_event_ids=field.provenance.evidence_event_ids,
    )


def project_mist(
    incident: IncidentRecord,
    events: Iterable[StoredEvent],
    *,
    now: datetime,
    viewer_role: str = ROLE_PRIMARY,
    policy: FreshnessPolicy | None = None,
    snapshot: SceneSnapshot | None = None,
    through_sequence: int | None = None,
) -> MistReport:
    """Project MIST from the same events that produce the scene snapshot.

    Passing an existing ``snapshot`` guarantees the handoff page and the cheat
    sheet describe the same revision instead of two independent summaries.
    """
    _require_capability(viewer_role, READ_MIST)
    materialised = tuple(events)
    snapshot = snapshot or project_scene_snapshot(
        incident,
        materialised,
        now=now,
        policy=policy,
        through_sequence=through_sequence,
    )

    selected = [
        event
        for event in materialised
        if through_sequence is None or event.server_sequence <= through_sequence
    ]
    effective = resolve_effective_events(selected)

    recommended: list[JsonDict] = []
    issued: list[JsonDict] = []
    acknowledged: list[JsonDict] = []

    for item in effective:
        if item.retracted:
            continue
        event = item.event
        detail = item.detail
        if event.type == et.DECISION_COMMITTED:
            recommended.append(
                {
                    "eventId": event.event_id,
                    "ruleVersion": detail.get("ruleVersion", event.envelope.rule_version),
                    "fromState": detail.get("fromState"),
                    "toState": detail.get("toState"),
                    "reasonCode": detail.get("reasonCode"),
                    "templateId": detail.get("templateId"),
                    "actions": detail.get("actions", []),
                    "stateRevision": detail.get("stateRevision"),
                    "decidedAt": iso(item.observed_at),
                }
            )
        elif event.type == et.COMMAND_ISSUED:
            issued.append(
                {
                    "eventId": event.event_id,
                    "commandId": detail.get("commandId"),
                    "command": detail.get("command"),
                    "modeRevision": event.envelope.mode_revision,
                    "authorityEpoch": event.envelope.authority_epoch,
                    "issuedAt": iso(item.observed_at),
                }
            )
        elif event.type == et.COMMAND_ACKNOWLEDGED:
            acknowledged.append(
                {
                    "eventId": event.event_id,
                    "commandId": detail.get("commandId"),
                    "result": detail.get("result"),
                    "acknowledgedAt": iso(item.observed_at),
                }
            )

    return MistReport(
        incident_id=incident.incident_id,
        snapshot_revision=snapshot.snapshot_revision,
        generated_through_revision=snapshot.generated_through_revision,
        generated_through_sequence=snapshot.generated_through_sequence,
        mechanism=tuple(_entry(key, snapshot) for key in et.MIST_MECHANISM_KEYS),
        injuries=tuple(_entry(key, snapshot) for key in et.MIST_INJURY_KEYS),
        signs=tuple(_entry(key, snapshot) for key in et.MIST_SIGN_KEYS),
        reported_actions=snapshot.actions_performed,
        recommended_actions=tuple(recommended),
        issued_commands=tuple(issued),
        device_acknowledgements=tuple(acknowledged),
    )


def encode_cursor(server_sequence: int) -> str:
    return f"{_CURSOR_PREFIX}{server_sequence}"


def decode_cursor(cursor: str | None) -> int | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor.startswith(_CURSOR_PREFIX):
        raise ServiceError(INVALID_INPUT, "malformed_cursor", detail={"cursor": cursor})
    raw = cursor[len(_CURSOR_PREFIX) :]
    if not raw.isascii() or not raw.isdigit() or len(raw) > _MAX_CURSOR_NUMBER_DIGITS:
        raise ServiceError(INVALID_INPUT, "malformed_cursor", detail={"cursor": cursor})
    return int(raw)


def _sanitize_detail(
    event_type: str, detail: Mapping[str, Any], allowlist: dict[str, tuple[str, ...]] | None
) -> JsonDict:
    if allowlist is None:
        return dict(detail)
    permitted = allowlist.get(event_type)
    if permitted is None:
        return {}
    return {name: detail[name] for name in permitted if name in detail}


def build_handoff_timeline(
    events: Iterable[StoredEvent],
    *,
    viewer_role: str,
    cursor: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_page_size: int = MAX_PAGE_SIZE,
) -> TimelinePage:
    """Return one bounded, sanitized page of the incident timeline.

    An AED runner and an ambulance greeter have no timeline capability at all,
    so they are refused here rather than served an emptied page.
    """
    _require_capability(viewer_role, READ_TIMELINE)
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        raise ServiceError(
            INVALID_INPUT, "invalid_page_size", detail={"pageSize": page_size}
        )
    effective_page_size = min(page_size, max_page_size)
    after = decode_cursor(cursor)

    allowlist = ROLE_DETAIL_ALLOWLIST.get(viewer_role, HANDOFF_DETAIL_ALLOWLIST)
    materialised = tuple(events)
    roots = correction_roots(ordered_events(materialised))
    corrected_by: dict[str, list[str]] = {}
    for correction_id, root_id in roots.items():
        corrected_by.setdefault(root_id, []).append(correction_id)

    in_receipt_order = sorted(materialised, key=lambda event: event.server_sequence)
    remaining = [
        event
        for event in in_receipt_order
        if after is None or event.server_sequence > after
    ]
    window = remaining[:effective_page_size]
    has_more = len(remaining) > len(window)

    entries = tuple(
        TimelineEntry(
            event_id=event.event_id,
            type=event.type,
            server_sequence=event.server_sequence,
            client_time=event.envelope.client_time,
            server_time=event.server_time,
            detail=_sanitize_detail(event.type, event.detail, allowlist),
            source=event.envelope.source,
            actor_role=event.actor_role,
            corrects_event_id=(
                event.detail.get("correctsEventId")
                if event.type == et.EVENT_CORRECTED
                else None
            ),
            corrected_by_event_ids=tuple(sorted(corrected_by.get(event.event_id, ()))),
        )
        for event in window
    )

    next_cursor = encode_cursor(window[-1].server_sequence) if window and has_more else None
    generated_through = (
        in_receipt_order[-1].server_sequence if in_receipt_order else 0
    )
    return TimelinePage(
        entries=entries,
        next_cursor=next_cursor,
        has_more=has_more,
        page_size=effective_page_size,
        generated_through_sequence=generated_through,
        viewer_role=viewer_role,
    )


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "HANDOFF_DETAIL_ALLOWLIST",
    "MAX_PAGE_SIZE",
    "ROLE_DETAIL_ALLOWLIST",
    "build_handoff_timeline",
    "decode_cursor",
    "encode_cursor",
    "project_mist",
]
