"""Scenario: switching between call, voice guidance and handover.

Mirrors demonstration scenario 3 in ``docs/sdd.md`` section 12. The rescuer
dials 119, records facts silently during the call, reports that the call
ended, moves to voice guidance, then redials. The data layer must:

* keep interaction mode, clinical state and incident status separate;
* advance ``modeRevision`` monotonically and reject a replayed mode event;
* preserve every reported action across each switch;
* treat a call report as a user statement that does not move the mode by
  itself.
"""

from __future__ import annotations

from typing import Any

from app.services.incident import event_types as et
from app.services.incident import project_scene_snapshot

from .support import EventFactory, ack_summary, build_world, conflict_summary

NAME = "call_switching"
DESCRIPTION = "Dial, silent recording, call end, voice guidance, redial, handover."


def run() -> dict[str, Any]:
    world = build_world(NAME)
    primary = world.primary()
    factory = EventFactory(NAME)
    steps: list[dict[str, Any]] = []

    def ingest(payloads: list[dict[str, Any]], label: str) -> Any:
        result = world.ingestion.ingest_batch(
            world.incident_id, payloads, principal=primary
        )
        steps.append(
            {
                "step": label,
                "acknowledgements": ack_summary(result.acknowledgements),
                "conflicts": conflict_summary(result.conflicts),
                "interactionMode": result.incident.interaction_mode,
                "modeRevision": result.incident.mode_revision,
            }
        )
        return result

    # 1. Dial. The browser closes its audio gate first and reports the attempt;
    #    the attempt is not evidence that a call connected.
    factory.mode_revision = 1
    ingest(
        [
            factory.build(
                et.CALL_REPORTED,
                {"reportedState": "dial_started"},
                offset_seconds=5,
                label="dial",
            ),
            factory.build(
                et.MODE_CHANGED,
                {"mode": "on_call", "modeRevision": 1},
                offset_seconds=5.5,
                label="enter-on-call",
            ),
        ],
        "dial_and_enter_call_mode",
    )

    # 2. Silent recording while the dispatcher leads.
    ingest(
        [
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {"key": "patient.responsive", "value": False},
                offset_seconds=40,
                label="responsive",
            ),
            factory.build(
                et.OBSERVATION_CONFIRMED,
                {"key": "patient.breathing", "value": False},
                offset_seconds=45,
                label="breathing",
            ),
            factory.build(
                et.ACTION_REPORTED,
                {"action": "cpr_started"},
                offset_seconds=60,
                source="button",
                label="cpr",
            ),
        ],
        "record_during_call",
    )

    # 3. A replayed mode event from the previous revision must not reopen the
    #    older mode.
    stale = ingest(
        [
            factory.build(
                et.MODE_CHANGED,
                {"mode": "call_119", "modeRevision": 1},
                offset_seconds=70,
                label="replayed-mode",
            )
        ],
        "replayed_mode_event_rejected",
    )

    # 4. The user reports the call ended, then activates voice guidance.
    factory.mode_revision = 2
    ingest(
        [
            factory.build(
                et.CALL_REPORTED,
                {"reportedState": "call_ended"},
                offset_seconds=120,
                label="call-ended",
            ),
        ],
        "call_end_reported_without_mode_change",
    )
    mode_after_call_report = world.ingestion.get_incident(
        world.incident_id
    ).interaction_mode

    ingest(
        [
            factory.build(
                et.MODE_CHANGED,
                {"mode": "voice_guidance", "modeRevision": 2},
                offset_seconds=121,
                label="enter-voice",
            )
        ],
        "enter_voice_guidance",
    )

    # 5. Redial: back to on_call at a higher revision.
    factory.mode_revision = 3
    ingest(
        [
            factory.build(
                et.CALL_REPORTED,
                {"reportedState": "dial_started"},
                offset_seconds=200,
                label="redial",
            ),
            factory.build(
                et.MODE_CHANGED,
                {"mode": "on_call", "modeRevision": 3},
                offset_seconds=201,
                label="redial-mode",
            ),
        ],
        "redial",
    )

    # 6. EMS arrives; the incident moves to handover.
    factory.mode_revision = 4
    factory.state_revision = 1
    ingest(
        [
            factory.build(
                et.ACTION_REPORTED,
                {"action": "ems_arrived"},
                offset_seconds=400,
                source="button",
                label="ems-arrived",
            ),
            factory.build(
                et.MODE_CHANGED,
                {"mode": "handover", "modeRevision": 4},
                offset_seconds=401,
                label="handover-mode",
            ),
            factory.build(
                et.INCIDENT_STATE_UPDATED,
                {"status": "handed_over", "stateRevision": 1},
                offset_seconds=402,
                label="handed-over",
            ),
        ],
        "handover",
    )

    incident = world.ingestion.get_incident(world.incident_id)
    snapshot = project_scene_snapshot(
        incident, world.all_events(), now=world.now()
    )
    actions = [action.action for action in snapshot.actions_performed]

    return {
        "scenario": NAME,
        "description": DESCRIPTION,
        "incidentId": world.incident_id,
        "steps": steps,
        "staleModeConflicts": conflict_summary(stale.conflicts),
        "modeAfterCallEndReport": mode_after_call_report,
        "finalInteractionMode": incident.interaction_mode,
        "finalModeRevision": incident.mode_revision,
        "finalStatus": incident.status,
        "callStatus": incident.call_status,
        "actionsPreserved": actions,
        "snapshotRevision": snapshot.snapshot_revision,
        "eventCount": world.events.count(world.incident_id),
    }


__all__ = ["DESCRIPTION", "NAME", "run"]
