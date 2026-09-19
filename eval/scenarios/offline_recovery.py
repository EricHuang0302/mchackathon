"""Scenario: offline recording, interrupted sync and reconnect.

Mirrors demonstration scenario 5 in ``docs/sdd.md`` section 12. A prepared
primary session loses connectivity, keeps recording locally, and reconnects.
The data layer must:

* accept a retried batch as duplicates without changing stored history;
* resume from the last contiguously acknowledged client sequence after an
  interrupted upload;
* project out-of-order local events into the same snapshot as an in-order
  upload, because client occurrence order drives the projection;
* reject a stale revision instead of overwriting newer state;
* return a mode revision that is never behind the client's, so a reconnect
  cannot unmute an ongoing call;
* hand back catch-up events that are record-only, never re-executed.
"""

from __future__ import annotations

from typing import Any

from app.services.incident import event_types as et
from app.services.incident import project_scene_snapshot
from app.services.incident.reconciliation import ResyncRequest

from .support import EventFactory, ack_summary, build_world, conflict_summary

NAME = "offline_recovery"
DESCRIPTION = "Offline recording, duplicate batch, out-of-order upload, reconnect."


def content_summary(snapshot: Any) -> dict[str, Any]:
    """Snapshot content without receipt-time fields.

    ``receivedAt`` and ``updatedAt`` describe when the server received an
    event, so they legitimately differ between two upload orders. Everything
    else must match exactly.
    """
    payload = snapshot.to_dict()
    for section in payload["sections"].values():
        for item in section:
            item["provenance"].pop("receivedAt", None)
    payload.pop("updatedAt", None)
    payload.pop("expiresAt", None)
    payload.pop("generatedThroughSequence", None)
    payload.pop("generatedThroughEventId", None)
    return payload


def _offline_payloads(factory: EventFactory) -> list[dict[str, Any]]:
    """Six local events recorded while the browser had no connectivity."""
    return [
        factory.build(
            et.OBSERVATION_CONFIRMED,
            {"key": "patient.breathing", "value": False},
            offset_seconds=200,
            label="breathing",
        ),
        factory.build(
            et.ACTION_REPORTED,
            {"action": "cpr_started"},
            offset_seconds=210,
            source="button",
            label="cpr",
        ),
        factory.build(
            et.OBSERVATION_PROPOSED,
            {"key": "hazards.description", "value": "wet floor near entrance"},
            offset_seconds=215,
            source="camera_proposal",
            label="hazard",
        ),
        factory.build(
            et.ACTION_REPORTED,
            {"action": "aed_requested"},
            offset_seconds=240,
            source="button",
            label="aed",
        ),
        factory.build(
            et.OBSERVATION_CONFIRMED,
            {"key": "location.floor", "value": "3F"},
            offset_seconds=260,
            label="floor",
        ),
        factory.build(
            et.OBSERVATION_CONFIRMED,
            {"key": "location.entrance", "value": "north stairwell"},
            offset_seconds=280,
            label="entrance",
        ),
    ]


def _prelude(factory: EventFactory) -> list[dict[str, Any]]:
    return [
        factory.build(
            et.MODE_CHANGED,
            {"mode": "on_call", "modeRevision": 1},
            offset_seconds=5,
            label="enter-on-call",
        ),
        factory.build(
            et.OBSERVATION_CONFIRMED,
            {"key": "patient.responsive", "value": False},
            offset_seconds=30,
            label="responsive",
        ),
    ]


def run() -> dict[str, Any]:
    world = build_world(NAME)
    primary = world.primary()
    factory = EventFactory(NAME)

    factory.mode_revision = 1
    prelude = _prelude(factory)
    world.ingestion.ingest_batch(world.incident_id, prelude, principal=primary)

    offline = _offline_payloads(factory)
    last_offline_sequence = factory.last_client_sequence

    # The upload is interrupted after three of six events.
    partial = world.ingestion.ingest_batch(
        world.incident_id, offline[:3], principal=primary
    )
    resume_after_interruption = partial.incident.last_acknowledged_client_sequence(
        factory.client_id
    )

    # The client retries the same batch: every event is a duplicate and the
    # stored history is unchanged.
    before_retry = world.events.count(world.incident_id)
    retry = world.ingestion.ingest_batch(
        world.incident_id, offline[:3], principal=primary
    )
    after_retry = world.events.count(world.incident_id)

    # The remaining events arrive out of their occurrence order.
    reordered = [offline[5], offline[3], offline[4]]
    out_of_order = world.ingestion.ingest_batch(
        world.incident_id, reordered, principal=primary
    )

    # A replayed mode event from the pre-outage revision must not win.
    factory.mode_revision = 1
    stale = world.ingestion.ingest_batch(
        world.incident_id,
        [
            factory.build(
                et.MODE_CHANGED,
                {"mode": "call_119", "modeRevision": 1},
                offset_seconds=300,
                label="stale-mode",
            )
        ],
        principal=primary,
    )

    # Reconnect. The browser advanced its own authority epoch during the
    # outage and holds a newer mode revision than the server.
    resync = world.reconciliation.reconcile(
        world.incident_id,
        ResyncRequest(
            client_id=factory.client_id,
            client_instance_id=factory.client_instance_id,
            interaction_mode="on_call",
            mode_revision=2,
            authority_epoch=1,
            last_acknowledged_client_sequence=last_offline_sequence,
            known_server_sequence=0,
        ),
        principal=primary,
    )

    # Control world: the same events ingested strictly in occurrence order.
    control = build_world(NAME + "_control")
    control_primary = control.primary()
    control_factory = EventFactory(NAME)
    control_factory.mode_revision = 1
    control.ingestion.ingest_batch(
        control.incident_id, _prelude(control_factory), principal=control_primary
    )
    control.ingestion.ingest_batch(
        control.incident_id,
        _offline_payloads(control_factory),
        principal=control_primary,
    )

    observed = project_scene_snapshot(
        world.ingestion.get_incident(world.incident_id),
        world.all_events(),
        now=world.now(),
    )
    expected = project_scene_snapshot(
        control.ingestion.get_incident(control.incident_id),
        control.all_events(),
        now=control.now(),
    )
    observed_summary = content_summary(observed)
    expected_summary = content_summary(expected)
    expected_summary["incidentId"] = observed_summary["incidentId"]

    return {
        "scenario": NAME,
        "description": DESCRIPTION,
        "incidentId": world.incident_id,
        "resumeAfterInterruption": resume_after_interruption,
        "retryAcknowledgements": ack_summary(retry.acknowledgements),
        "retryAddedEvents": after_retry - before_retry,
        "outOfOrderAcknowledgements": ack_summary(out_of_order.acknowledgements),
        "staleModeConflicts": conflict_summary(stale.conflicts),
        "reconcile": {
            "interactionMode": resync.interaction_mode,
            "modeRevision": resync.mode_revision,
            "modePreserved": resync.mode_preserved,
            "authorityEpoch": resync.authority_epoch,
            "resumeFromClientSequence": resync.resume_from_client_sequence,
            "replayEventCount": len(resync.replay_events),
            "replayExecutionAllowed": resync.replay_execution_allowed,
            "catchUpComplete": resync.catch_up_complete,
            "conflicts": conflict_summary(resync.conflicts),
        },
        "snapshotMatchesInOrderProjection": observed_summary == expected_summary,
        "snapshotRevision": observed.snapshot_revision,
        "eventCount": world.events.count(world.incident_id),
    }


__all__ = ["DESCRIPTION", "NAME", "content_summary", "run"]
