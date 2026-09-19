"""Scenario: snapshot-first EMS handoff.

Mirrors demonstration scenario 4 in ``docs/sdd.md`` section 12. The EMS viewer
gets the scene snapshot first, then evidence-backed MIST, then a bounded
timeline. The data layer must:

* keep a confirmed fact safe from a later model or camera proposal, while
  still surfacing the proposal for explicit confirmation;
* keep recommendations, issued commands, device acknowledgements and reported
  actions in four separate lists;
* leave an unreported fact ``unknown`` rather than inventing a value;
* show a correction next to the original event it references;
* refuse the timeline to an ambulance greeter and refuse clinical projections
  to an AED runner.

An AED that cannot be collected appears only as an input ``helper.updated``
event. Candidate selection and reassignment belong to the AED service and are
deliberately not exercised here.
"""

from __future__ import annotations

from typing import Any

from app.services.incident import (
    ROLE_AED_RUNNER,
    ROLE_AMBULANCE_GREETER,
    ROLE_CAPABILITIES,
    ROLE_EMS_VIEWER,
    ROLE_PRIMARY,
    ServiceError,
    build_handoff_timeline,
    project_mist,
    project_scene_snapshot,
)
from app.services.incident import event_types as et
from app.services.incident.access import READ_SCENE_SNAPSHOT, READ_TIMELINE

from .support import EventFactory, build_world

NAME = "snapshot_first_handoff"
DESCRIPTION = "Scene snapshot, evidence-backed MIST, bounded sanitized timeline."

HELPER_RUNNER_ID = "synthetic-runner-1"


def _denied(callable_: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        callable_(*args, **kwargs)
    except ServiceError as exc:
        return {"denied": True, "code": exc.code, "reason": exc.reason}
    return {"denied": False}


def run() -> dict[str, Any]:
    world = build_world(NAME)
    primary = world.primary()
    factory = EventFactory(NAME)
    factory.mode_revision = 1

    world.ingestion.ingest_batch(
        world.incident_id,
        [
            factory.build(
                et.MODE_CHANGED,
                {"mode": "on_call", "modeRevision": 1},
                offset_seconds=5,
                label="enter-on-call",
            ),
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {
                    "key": "location.address",
                    "value": "Synthetic Demo Building, Example Road 1",
                },
                offset_seconds=20,
                label="address",
            ),
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {"key": "location.floor", "value": "3F"},
                offset_seconds=25,
                label="floor",
            ),
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {"key": "circumstances.whatHappened", "value": "collapsed at desk"},
                offset_seconds=30,
                label="mechanism",
            ),
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {"key": "patient.responsive", "value": False},
                offset_seconds=35,
                label="responsive",
            ),
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {"key": "patient.breathing", "value": False},
                offset_seconds=40,
                label="breathing",
            ),
        ],
        principal=primary,
    )

    # A camera proposal arrives after the fact was confirmed. It must not
    # replace the confirmed value, and it must stay visible as pending.
    contradiction = world.ingestion.ingest_batch(
        world.incident_id,
        [
            factory.build(
                et.OBSERVATION_PROPOSED,
                {"key": "patient.breathing", "value": True},
                offset_seconds=50,
                source="camera_proposal",
                label="camera-breathing",
            ),
            factory.build(
                et.OBSERVATION_PROPOSED,
                {"key": "hazards.description", "value": "possible spill"},
                offset_seconds=52,
                source="camera_proposal",
                label="camera-hazard",
            ),
        ],
        principal=primary,
    )

    # Rule decision, issued command, device acknowledgement and a user report
    # about the same treatment: four separate claims.
    factory.state_revision = 0
    world.ingestion.ingest_batch(
        world.incident_id,
        [
            factory.build(
                et.DECISION_COMMITTED,
                {
                    "ruleVersion": factory.rule_version,
                    "fromState": "assessment",
                    "toState": "cpr",
                    "reasonCode": "no_breathing",
                    "templateId": "cpr.start",
                    "expectedStateRevision": 0,
                    "stateRevision": 1,
                    "actions": ["start_metronome"],
                },
                offset_seconds=60,
                source="rule_engine",
                label="decision",
            ),
            factory.build(
                et.COMMAND_ISSUED,
                {"commandId": "cmd-metronome-1", "command": "start_metronome"},
                offset_seconds=61,
                source="rule_engine",
                label="command",
            ),
            factory.build(
                et.COMMAND_ACKNOWLEDGED,
                {"commandId": "cmd-metronome-1", "result": "started"},
                offset_seconds=62,
                source="device",
                label="ack",
            ),
            factory.build(
                et.ACTION_REPORTED,
                {"action": "cpr_started"},
                offset_seconds=70,
                source="button",
                label="cpr",
            ),
        ],
        principal=primary,
    )

    # A mistyped bystander count, then a correction that references it.
    miscount = factory.build(
        et.OBSERVATION_CONFIRMED,
        {"key": "people.bystanderCount", "value": 12},
        offset_seconds=80,
        label="bystanders",
    )
    world.ingestion.ingest_batch(world.incident_id, [miscount], principal=primary)
    world.ingestion.ingest_batch(
        world.incident_id,
        [
            factory.build(
                et.EVENT_CORRECTED,
                {
                    "correctsEventId": miscount["eventId"],
                    "reason": "mistyped_count",
                    "detail": {"value": 2},
                },
                offset_seconds=85,
                label="correct-bystanders",
            )
        ],
        principal=primary,
    )

    # The AED runner reports the device could not be collected. This is input
    # only: choosing a replacement destination is the AED service's job.
    runner = world.helper("synthetic-runner-uid", ROLE_AED_RUNNER, HELPER_RUNNER_ID)
    world.ingestion.ingest_batch(
        world.incident_id,
        [
            EventFactory(
                NAME, client_id="synthetic-runner-client",
                client_instance_id="synthetic-runner-tab",
            ).build(
                et.HELPER_UPDATED,
                {
                    "helperId": HELPER_RUNNER_ID,
                    "role": ROLE_AED_RUNNER,
                    "status": "unavailable",
                    "reason": "cabinet_locked",
                },
                offset_seconds=90,
                source="helper_report",
                label="aed-unavailable",
            )
        ],
        principal=runner,
    )

    incident = world.ingestion.get_incident(world.incident_id)
    events = world.all_events()
    now = world.now()

    snapshot = project_scene_snapshot(incident, events, now=now)
    mist = project_mist(
        incident, events, now=now, viewer_role=ROLE_EMS_VIEWER, snapshot=snapshot
    )

    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = build_handoff_timeline(
            events, viewer_role=ROLE_EMS_VIEWER, cursor=cursor, page_size=5
        )
        pages.append(
            {
                "entryCount": len(page.entries),
                "types": [entry.type for entry in page.entries],
                "nextCursor": page.next_cursor,
                "hasMore": page.has_more,
            }
        )
        cursor = page.next_cursor
        if cursor is None:
            break

    breathing = snapshot.field_for("patient.breathing")
    hazard = snapshot.field_for("hazards.description")
    bystanders = snapshot.field_for("people.bystanderCount")
    unreported = snapshot.field_for("patient.pulse")

    primary_page = build_handoff_timeline(
        events, viewer_role=ROLE_PRIMARY, page_size=100
    )
    ems_page = build_handoff_timeline(
        events, viewer_role=ROLE_EMS_VIEWER, page_size=100
    )
    helper_rows = [
        entry.detail
        for entry in ems_page.entries
        if entry.type == et.HELPER_UPDATED
    ]

    return {
        "scenario": NAME,
        "description": DESCRIPTION,
        "incidentId": world.incident_id,
        "contradictionConflicts": [c.reason for c in contradiction.conflicts],
        "confirmedBreathing": {
            "value": breathing.value,
            "confirmation": breathing.provenance.confirmation,
            "pendingProposalValues": [
                proposal["value"] for proposal in breathing.pending_proposals
            ],
        },
        "cameraProposedHazard": {
            "value": hazard.value,
            "confirmation": hazard.provenance.confirmation,
        },
        "correctedBystanderCount": {
            "value": bystanders.value,
            "confirmation": bystanders.provenance.confirmation,
            "correctionEventIds": list(
                bystanders.provenance.corrected_from_event_ids
            ),
        },
        "unreportedField": {
            "key": unreported.key,
            "value": unreported.value,
            "confirmation": unreported.provenance.confirmation,
            "evidenceEventIds": list(unreported.provenance.evidence_event_ids),
        },
        "snapshotRevision": snapshot.snapshot_revision,
        "generatedThroughRevision": snapshot.generated_through_revision,
        "mist": {
            "mechanism": [entry.to_dict() for entry in mist.mechanism],
            "signs": [entry.to_dict() for entry in mist.signs],
            "reportedActions": [a.action for a in mist.reported_actions],
            "recommendedActionCount": len(mist.recommended_actions),
            "issuedCommandCount": len(mist.issued_commands),
            "deviceAcknowledgementCount": len(mist.device_acknowledgements),
            "unknownInjuryKeys": [
                entry.key for entry in mist.injuries if entry.confirmation == et.UNKNOWN
            ],
        },
        "timelinePages": pages,
        "originalAndCorrectionBothPresent": _correction_pairing(primary_page),
        "sanitizedHelperRows": helper_rows,
        "primaryDetailKeysForDecision": sorted(
            next(
                entry.detail
                for entry in primary_page.entries
                if entry.type == et.DECISION_COMMITTED
            )
        ),
        "emsDetailKeysForDecision": sorted(
            next(
                entry.detail
                for entry in ems_page.entries
                if entry.type == et.DECISION_COMMITTED
            )
        ),
        "greeterTimeline": _denied(
            build_handoff_timeline, events, viewer_role=ROLE_AMBULANCE_GREETER
        ),
        "runnerTimeline": _denied(
            build_handoff_timeline, events, viewer_role=ROLE_AED_RUNNER
        ),
        "runnerMist": _denied(
            project_mist, incident, events, now=now, viewer_role=ROLE_AED_RUNNER
        ),
        "greeterCanReadSnapshot": READ_SCENE_SNAPSHOT
        in ROLE_CAPABILITIES[ROLE_AMBULANCE_GREETER],
        "runnerCanReadSnapshot": READ_SCENE_SNAPSHOT
        in ROLE_CAPABILITIES[ROLE_AED_RUNNER],
        "emsCanReadTimeline": READ_TIMELINE in ROLE_CAPABILITIES[ROLE_EMS_VIEWER],
        "eventCount": world.events.count(world.incident_id),
    }


def _correction_pairing(page: Any) -> dict[str, Any]:
    corrections = [
        entry for entry in page.entries if entry.type == et.EVENT_CORRECTED
    ]
    originals = [
        entry for entry in page.entries if entry.corrected_by_event_ids
    ]
    return {
        "correctionCount": len(corrections),
        "originalsStillPresent": len(originals),
        "links": [
            {
                "correction": entry.event_id,
                "corrects": entry.corrects_event_id,
            }
            for entry in corrections
        ],
    }


__all__ = ["DESCRIPTION", "NAME", "run"]
