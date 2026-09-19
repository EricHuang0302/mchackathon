"""MIST projection and the bounded, sanitized handoff timeline."""

from __future__ import annotations

import pytest

from app.services.incident import (
    ROLE_AED_RUNNER,
    ROLE_AMBULANCE_GREETER,
    ROLE_EMS_VIEWER,
    ROLE_PRIMARY,
    ServiceError,
    build_handoff_timeline,
    project_mist,
    project_scene_snapshot,
)
from app.services.incident import event_types as et
from app.services.incident.handoff import HANDOFF_DETAIL_ALLOWLIST, decode_cursor


def mist_for(world, viewer_role: str = ROLE_EMS_VIEWER):
    return project_mist(
        world.incident, world.all_events, now=world.now(), viewer_role=viewer_role
    )


def test_an_empty_incident_reports_only_unknowns(world) -> None:
    report = mist_for(world)
    entries = [*report.mechanism, *report.injuries, *report.signs]

    assert entries, "MIST must still list its keys for an empty incident"
    for entry in entries:
        assert entry.value is None
        assert entry.confirmation == et.UNKNOWN
        assert entry.evidence_event_ids == ()
    assert report.reported_actions == ()
    assert report.recommended_actions == ()
    assert report.issued_commands == ()
    assert report.device_acknowledgements == ()


def test_mist_entries_carry_the_events_that_justify_them(world, factory) -> None:
    observation = factory.build(
        et.OBSERVATION_CONFIRMED,
        {"key": "circumstances.whatHappened", "value": "collapsed at desk"},
        at=10,
    )
    world.ingest([observation])

    mechanism = {entry.key: entry for entry in mist_for(world).mechanism}
    entry = mechanism["circumstances.whatHappened"]
    assert entry.value == "collapsed at desk"
    assert entry.confirmation == "confirmed"
    assert observation["eventId"] in entry.evidence_event_ids


def test_treatment_claims_stay_in_four_separate_lists(world, factory) -> None:
    world.ingest(
        [
            factory.build(
                et.DECISION_COMMITTED,
                {
                    "toState": "cpr",
                    "reasonCode": "no_breathing",
                    "templateId": "cpr.start",
                    "stateRevision": 1,
                    "actions": ["start_metronome"],
                },
                at=10,
                source="rule_engine",
            ),
            factory.build(
                et.COMMAND_ISSUED,
                {"commandId": "cmd-1", "command": "start_metronome"},
                at=11,
                source="rule_engine",
            ),
            factory.build(
                et.COMMAND_ACKNOWLEDGED,
                {"commandId": "cmd-1", "result": "started"},
                at=12,
                source="device",
            ),
            factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=20, source="button"),
        ]
    )
    report = mist_for(world)

    assert [a.action for a in report.reported_actions] == ["cpr_started"]
    assert [r["templateId"] for r in report.recommended_actions] == ["cpr.start"]
    assert [c["commandId"] for c in report.issued_commands] == ["cmd-1"]
    assert [a["result"] for a in report.device_acknowledgements] == ["started"]


def test_mist_reuses_a_supplied_snapshot_revision(world, factory) -> None:
    world.ingest([factory.build(et.OBSERVATION_CONFIRMED, {"key": "patient.breathing", "value": False}, at=10)])
    snapshot = project_scene_snapshot(world.incident, world.all_events, now=world.now())
    report = project_mist(
        world.incident,
        world.all_events,
        now=world.now(),
        viewer_role=ROLE_EMS_VIEWER,
        snapshot=snapshot,
    )
    assert report.snapshot_revision == snapshot.snapshot_revision
    assert report.generated_through_sequence == snapshot.generated_through_sequence


def test_runner_is_refused_mist_and_timeline(world, factory) -> None:
    world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10, source="button")])

    with pytest.raises(ServiceError) as mist_error:
        mist_for(world, viewer_role=ROLE_AED_RUNNER)
    assert mist_error.value.code == "unauthorized"

    with pytest.raises(ServiceError) as timeline_error:
        build_handoff_timeline(world.all_events, viewer_role=ROLE_AED_RUNNER)
    assert timeline_error.value.code == "unauthorized"


def test_greeter_is_refused_the_timeline_but_keeps_the_snapshot(world, factory) -> None:
    world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10, source="button")])

    with pytest.raises(ServiceError):
        build_handoff_timeline(world.all_events, viewer_role=ROLE_AMBULANCE_GREETER)

    from app.services.incident import ROLE_CAPABILITIES
    from app.services.incident.access import READ_SCENE_SNAPSHOT

    assert READ_SCENE_SNAPSHOT in ROLE_CAPABILITIES[ROLE_AMBULANCE_GREETER]


def test_unknown_viewer_role_is_refused(world) -> None:
    with pytest.raises(ServiceError) as excinfo:
        build_handoff_timeline(world.all_events, viewer_role="auditor")
    assert excinfo.value.reason == "unknown_viewer_role"


def test_timeline_detail_is_allowlisted_per_role(world, factory) -> None:
    world.ingest(
        [
            factory.build(
                et.DECISION_COMMITTED,
                {
                    "toState": "cpr",
                    "reasonCode": "no_breathing",
                    "templateId": "cpr.start",
                    "stateRevision": 1,
                    "expectedStateRevision": 0,
                    "actions": ["start_metronome"],
                    "internalPromptId": "must-not-leak",
                },
                at=10,
                source="rule_engine",
            ),
            factory.build(
                et.HELPER_UPDATED,
                {
                    "helperId": "runner-1",
                    "role": ROLE_AED_RUNNER,
                    "status": "en_route",
                    "location": {"lat": 25.0, "lng": 121.5},
                    "locationAccuracy": 8,
                },
                at=20,
            ),
        ]
    )

    ems = {e.type: e.detail for e in build_handoff_timeline(world.all_events, viewer_role=ROLE_EMS_VIEWER).entries}
    primary = {e.type: e.detail for e in build_handoff_timeline(world.all_events, viewer_role=ROLE_PRIMARY).entries}

    assert set(ems[et.DECISION_COMMITTED]) <= set(HANDOFF_DETAIL_ALLOWLIST[et.DECISION_COMMITTED])
    assert "internalPromptId" not in ems[et.DECISION_COMMITTED]
    assert "actions" not in ems[et.DECISION_COMMITTED]
    assert ems[et.HELPER_UPDATED] == {
        "helperId": "runner-1",
        "role": ROLE_AED_RUNNER,
        "status": "en_route",
    }
    # The primary session keeps its own full record.
    assert primary[et.DECISION_COMMITTED]["internalPromptId"] == "must-not-leak"
    assert "location" in primary[et.HELPER_UPDATED]


def test_an_unlisted_event_type_is_emptied_rather_than_leaked(world, factory) -> None:
    """A type absent from the allowlist yields an empty detail, not raw fields."""
    world.ingest([factory.build(et.TIMER_ELAPSED, {"timerId": "t1", "label": "cpr_cycle", "secret": "x"}, at=10)])
    entry = build_handoff_timeline(world.all_events, viewer_role=ROLE_EMS_VIEWER).entries[0]
    assert entry.detail == {"timerId": "t1", "label": "cpr_cycle"}


def test_timeline_pages_are_bounded_with_a_stable_cursor(world, factory) -> None:
    for index in range(12):
        world.ingest([factory.build(et.ACTION_REPORTED, {"action": f"step_{index}"}, at=index, source="button")])

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page = build_handoff_timeline(
            world.all_events, viewer_role=ROLE_EMS_VIEWER, cursor=cursor, page_size=5
        )
        pages += 1
        assert len(page.entries) <= 5
        seen.extend(entry.event_id for entry in page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert pages == 3
    assert len(seen) == 12
    assert len(set(seen)) == 12

    # Re-requesting the same cursor returns the same page.
    first = build_handoff_timeline(world.all_events, viewer_role=ROLE_EMS_VIEWER, page_size=5)
    again = build_handoff_timeline(world.all_events, viewer_role=ROLE_EMS_VIEWER, page_size=5)
    assert [e.event_id for e in first.entries] == [e.event_id for e in again.entries]
    assert decode_cursor(first.next_cursor) == first.entries[-1].server_sequence


def test_page_size_is_capped(world, factory) -> None:
    for index in range(5):
        world.ingest([factory.build(et.ACTION_REPORTED, {"action": f"a{index}"}, at=index, source="button")])
    page = build_handoff_timeline(
        world.all_events, viewer_role=ROLE_EMS_VIEWER, page_size=10_000, max_page_size=3
    )
    assert page.page_size == 3
    assert len(page.entries) == 3
    assert page.has_more is True


@pytest.mark.parametrize(
    "cursor",
    ["", "1", "seq:abc", "seq:²", "offset:3", f"seq:{'9' * 5000}"],
)
def test_malformed_cursor_is_rejected(world, cursor) -> None:
    with pytest.raises(ServiceError) as excinfo:
        build_handoff_timeline(world.all_events, viewer_role=ROLE_EMS_VIEWER, cursor=cursor)
    assert excinfo.value.reason == "malformed_cursor"


@pytest.mark.parametrize("page_size", [0, -1, "5"])
def test_invalid_page_size_is_rejected(world, page_size) -> None:
    with pytest.raises(ServiceError) as excinfo:
        build_handoff_timeline(world.all_events, viewer_role=ROLE_EMS_VIEWER, page_size=page_size)
    assert excinfo.value.reason == "invalid_page_size"


def test_a_correction_and_its_original_are_linked_in_the_timeline(world, factory) -> None:
    original = factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10, source="button")
    world.ingest([original])
    correction = factory.build(
        et.EVENT_CORRECTED,
        {"correctsEventId": original["eventId"], "reason": "mistap", "retracted": True},
        at=20,
    )
    world.ingest([correction])

    entries = {e.event_id: e for e in build_handoff_timeline(world.all_events, viewer_role=ROLE_EMS_VIEWER).entries}
    assert entries[original["eventId"]].corrected_by_event_ids == (correction["eventId"],)
    assert entries[correction["eventId"]].corrects_event_id == original["eventId"]
    assert entries[correction["eventId"]].detail == {
        "correctsEventId": original["eventId"],
        "reason": "mistap",
        "retracted": True,
    }


def test_timeline_entries_never_expose_the_client_instance(world, factory) -> None:
    world.ingest([factory.build(et.ACTION_REPORTED, {"action": "cpr_started"}, at=10, source="button")])
    entry = build_handoff_timeline(world.all_events, viewer_role=ROLE_EMS_VIEWER).entries[0].to_dict()
    assert "clientInstanceId" not in entry
    assert "clientId" not in entry
    assert "actorId" not in entry
