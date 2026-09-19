"""Unavailable-AED reassignment: idempotency, revisions, and exhaustion."""

from __future__ import annotations

from app.services.aed.assignment import (
    AedAssignmentService,
    AssignmentStatus,
    InMemoryAssignmentStore,
    ReassignmentOutcome,
    UnavailabilityReport,
)
from app.services.aed.candidates import CandidateSearchConfig
from app.services.aed.routing import DeterministicFakeRouteProvider
from .conftest import HELPER_POINT, PATIENT_POINT, make_record

INCIDENT_ID = "incident-synthetic-1"
HELPER_ID = "helper-1"

NEAREST = "synthetic-demo:aed-near"
SECOND = "synthetic-demo:aed-mid"
THIRD = "synthetic-demo:aed-far"


def _records():
    return [
        make_record("aed-near", latitude=25.0472, longitude=121.5172),
        make_record("aed-mid", latitude=25.0480, longitude=121.5180),
        make_record("aed-far", latitude=25.0490, longitude=121.5190),
        # Published as closed at the test instant, so it is never dispatchable.
        make_record(
            "aed-closed",
            latitude=25.0473,
            longitude=121.5173,
            opening_hours="Mon-Fri 22:00-23:00",
        ),
    ]


def _service(records=None, provider=None) -> AedAssignmentService:
    return AedAssignmentService(
        records=records if records is not None else _records(),
        route_provider=provider or DeterministicFakeRouteProvider(),
        store=InMemoryAssignmentStore(),
        search_config=CandidateSearchConfig(radius_meters=1_000.0, limit=10),
    )


def _assign(service, now, helper):
    return service.assign(
        incident_id=INCIDENT_ID,
        helper_location=helper,
        patient_point=PATIENT_POINT,
        now=now,
    )


def _report(aed_id: str, revision: int, now, report_id: str) -> UnavailabilityReport:
    return UnavailabilityReport(
        report_id=report_id,
        incident_id=INCIDENT_ID,
        helper_id=HELPER_ID,
        aed_id=aed_id,
        reason_code="cabinet_locked",
        reported_at=now,
        expected_assignment_revision=revision,
    )


def _handle(service, report, now, helper):
    return service.report_unavailable(
        report,
        helper_location=helper,
        patient_point=PATIENT_POINT,
        now=now,
    )


def test_initial_assignment_selects_the_nearest_dispatchable_aed(now, fresh_helper):
    service = _service()

    result = _assign(service, now, fresh_helper)

    assert result.outcome is ReassignmentOutcome.ASSIGNED
    assert result.assignment is not None
    assert result.assignment.aed_id == NEAREST
    assert result.assignment.assignment_revision == 1
    assert result.assignment.status is AssignmentStatus.ASSIGNED
    assert result.assignment.estimate is not None


def test_unavailable_report_produces_exactly_one_revised_assignment(now, fresh_helper):
    """Scenario: unavailable candidate."""

    service = _service()
    _assign(service, now, fresh_helper)

    result = _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)

    assert result.outcome is ReassignmentOutcome.REASSIGNED
    assert result.assignment is not None
    assert result.assignment.aed_id == SECOND
    assert result.assignment.assignment_revision == 2
    assert result.assignment.previous_aed_id == NEAREST
    assert service.store.get_assignment(INCIDENT_ID) is result.assignment


def test_the_failed_candidate_is_excluded_from_later_searches(now, fresh_helper):
    service = _service()
    _assign(service, now, fresh_helper)

    result = _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)

    assert NEAREST in service.store.excluded_aed_ids(INCIDENT_ID)
    assert result.search is not None
    assert NEAREST not in {candidate.stable_id for candidate in result.search.candidates}


def test_replayed_report_identifier_is_idempotent(now, fresh_helper):
    """Scenario: repeated failure reports."""

    service = _service()
    _assign(service, now, fresh_helper)
    report = _report(NEAREST, 1, now, "report-1")

    first = _handle(service, report, now, fresh_helper)
    second = _handle(service, report, now, fresh_helper)

    assert second.deduplicated is True
    assert second.outcome is first.outcome
    assert second.assignment == first.assignment
    assert second.assignment.assignment_revision == 2
    assert service.store.get_assignment(INCIDENT_ID).assignment_revision == 2


def test_repeat_report_for_an_excluded_aed_with_an_old_revision_is_acknowledged(
    now, fresh_helper
):
    """A retry that still carries the pre-reassignment revision is a duplicate."""

    service = _service()
    _assign(service, now, fresh_helper)
    _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)

    retry = _handle(service, _report(NEAREST, 1, now, "report-1-retry"), now, fresh_helper)

    assert retry.outcome is ReassignmentOutcome.DUPLICATE_REPORT
    assert retry.deduplicated is True
    assert retry.assignment is not None
    assert retry.assignment.aed_id == SECOND
    assert retry.assignment.assignment_revision == 2


def test_stale_revision_for_the_current_aed_is_rejected(now, fresh_helper):
    service = _service()
    _assign(service, now, fresh_helper)
    _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)

    # A new report about the *current* AED that carries the old revision.
    stale = _handle(service, _report(SECOND, 1, now, "report-2"), now, fresh_helper)

    assert stale.outcome is ReassignmentOutcome.STALE_REVISION
    assert stale.assignment.aed_id == SECOND
    assert stale.assignment.assignment_revision == 2
    assert stale.changed_assignment is False


def test_report_for_a_non_current_aed_is_rejected_as_a_mismatch(now, fresh_helper):
    service = _service()
    _assign(service, now, fresh_helper)

    mismatch = _handle(service, _report(THIRD, 1, now, "report-x"), now, fresh_helper)

    assert mismatch.outcome is ReassignmentOutcome.AED_MISMATCH
    assert mismatch.assignment.aed_id == NEAREST
    assert mismatch.assignment.assignment_revision == 1


def test_report_for_a_different_helper_is_rejected(now, fresh_helper):
    service = _service()
    _assign(service, now, fresh_helper)
    report = _report(NEAREST, 1, now, "report-wrong-helper")
    report = UnavailabilityReport(
        report_id=report.report_id,
        incident_id=report.incident_id,
        helper_id="another-helper",
        aed_id=report.aed_id,
        reason_code=report.reason_code,
        reported_at=report.reported_at,
        expected_assignment_revision=report.expected_assignment_revision,
    )

    mismatch = _handle(service, report, now, fresh_helper)

    assert mismatch.outcome is ReassignmentOutcome.AED_MISMATCH
    assert mismatch.assignment.assignment_revision == 1
    assert service.store.excluded_aed_ids(INCIDENT_ID) == frozenset()


def test_report_without_an_existing_assignment_is_rejected(now, fresh_helper):
    service = _service()

    result = _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)

    assert result.outcome is ReassignmentOutcome.NOT_ASSIGNED
    assert result.assignment is None


def test_repeated_assign_calls_do_not_duplicate_the_assignment(now, fresh_helper):
    service = _service()
    first = _assign(service, now, fresh_helper)

    second = _assign(service, now, fresh_helper)

    assert second.deduplicated is True
    assert second.assignment == first.assignment
    assert second.assignment.assignment_revision == 1


def test_exhausting_every_candidate_reports_no_remaining_candidate(now, fresh_helper):
    """Scenario: no remaining candidate."""

    service = _service()
    _assign(service, now, fresh_helper)
    _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)
    _handle(service, _report(SECOND, 2, now, "report-2"), now, fresh_helper)

    final = _handle(service, _report(THIRD, 3, now, "report-3"), now, fresh_helper)

    assert final.outcome is ReassignmentOutcome.NO_CANDIDATE
    assert final.assignment is not None
    assert final.assignment.aed_id is None
    assert final.assignment.status is AssignmentStatus.NO_CANDIDATE
    assert final.assignment.assignment_revision == 4
    assert "no accessible AED candidate is known" in final.detail
    # The closed candidate is never recycled as a destination.
    assert set(final.excluded_aed_ids) == {NEAREST, SECOND, THIRD}


def test_no_candidate_result_is_idempotent_on_replay(now, fresh_helper):
    service = _service()
    _assign(service, now, fresh_helper)
    _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)
    _handle(service, _report(SECOND, 2, now, "report-2"), now, fresh_helper)
    report = _report(THIRD, 3, now, "report-3")
    first = _handle(service, report, now, fresh_helper)

    replay = _handle(service, report, now, fresh_helper)

    assert replay.deduplicated is True
    assert replay.outcome is first.outcome
    assert service.store.get_assignment(INCIDENT_ID).assignment_revision == 4


def test_published_closed_candidates_are_never_assigned(now, fresh_helper):
    service = _service(
        records=[
            make_record(
                "aed-closed",
                latitude=25.0472,
                longitude=121.5172,
                opening_hours="Mon-Fri 22:00-23:00",
            ),
            make_record("aed-open", latitude=25.0490, longitude=121.5190),
        ]
    )

    result = _assign(service, now, fresh_helper)

    assert result.assignment.aed_id == "synthetic-demo:aed-open"


def test_unknown_hours_candidate_is_assignable_with_visible_uncertainty(
    now, fresh_helper
):
    service = _service(
        records=[
            make_record(
                "aed-unknown",
                latitude=25.0472,
                longitude=121.5172,
                opening_hours="",
                access_notes=None,
            )
        ]
    )

    result = _assign(service, now, fresh_helper)

    assert result.assignment.aed_id == "synthetic-demo:aed-unknown"
    availability = result.assignment.candidate.availability
    assert availability.status.value == "unknown"
    assert "opening_hours_unknown" in availability.uncertainty
    assert "access_notes_unknown" in availability.uncertainty


def test_reassignment_estimate_survives_a_route_provider_failure(now, fresh_helper):
    """Reassignment still completes when routing is unavailable."""

    service = _service(
        provider=DeterministicFakeRouteProvider(fail_when=lambda origin, dest: True)
    )
    _assign(service, now, fresh_helper)

    result = _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)

    assert result.outcome is ReassignmentOutcome.REASSIGNED
    estimate = result.assignment.estimate
    assert estimate is not None
    assert estimate.fully_route_based is False
    assert any(code.startswith("outbound_straight_line") for code in estimate.uncertainty)


def test_helper_at_the_first_aed_still_reassigns_when_it_is_unavailable(now):
    """Scenario: helper standing at the AED reports it cannot be obtained."""

    from .conftest import helper_status_at

    service = _service()
    at_first = helper_status_at(
        make_record("aed-near", latitude=25.0472, longitude=121.5172).point,
        reported_at=now,
        now=now,
    )
    _assign(service, now, at_first)

    result = _handle(service, _report(NEAREST, 1, now, "report-1"), now, at_first)

    assert result.outcome is ReassignmentOutcome.REASSIGNED
    assert result.assignment.aed_id == SECOND
    # The helper is no longer at the new destination, so the outbound leg is real.
    assert result.assignment.estimate.outbound.duration_seconds > 0


def test_assignment_never_claims_physical_availability(now, fresh_helper):
    service = _service()

    result = _assign(service, now, fresh_helper)

    availability = result.assignment.candidate.availability
    # "open" is a published-hours statement, carrying its source provenance.
    assert availability.reason_code.startswith("published") or availability.reason_code.startswith(
        "within_published"
    )
    assert availability.dataset_version == "synthetic-2026-09-01"
    assert availability.source_updated_at is not None
    assert HELPER_POINT == fresh_helper.position.point


def test_retry_after_exhaustion_advances_the_revision_instead_of_restarting(
    now, fresh_helper
):
    service = _service()
    _assign(service, now, fresh_helper)
    _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)
    _handle(service, _report(SECOND, 2, now, "report-2"), now, fresh_helper)
    exhausted = _handle(service, _report(THIRD, 3, now, "report-3"), now, fresh_helper)
    assert exhausted.outcome is ReassignmentOutcome.NO_CANDIDATE

    retry = _assign(service, now, fresh_helper)

    assert retry.outcome is ReassignmentOutcome.NO_CANDIDATE
    assert retry.assignment.assignment_revision == 5


def test_previous_aed_id_names_only_the_directly_preceding_destination(
    now, fresh_helper
):
    service = _service()
    first = _assign(service, now, fresh_helper)
    assert first.assignment.previous_aed_id is None

    second = _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)
    assert second.assignment.previous_aed_id == NEAREST

    _handle(service, _report(SECOND, 2, now, "report-2"), now, fresh_helper)
    exhausted = _handle(service, _report(THIRD, 3, now, "report-3"), now, fresh_helper)
    assert exhausted.assignment.previous_aed_id == THIRD

    # After an exhausted search the preceding revision named no AED at all.
    retry = _assign(service, now, fresh_helper)
    assert retry.assignment.previous_aed_id is None


def test_out_of_order_report_is_rejected_then_accepted_only_once(now, fresh_helper):
    """A report that arrives before its revision is current is not cached.

    It is rejected on arrival, may succeed once state catches up, and then
    deduplicates like any other accepted report.
    """

    service = _service()
    _assign(service, now, fresh_helper)
    early = _report(SECOND, 2, now, "report-early")

    rejected = _handle(service, early, now, fresh_helper)
    assert rejected.outcome is ReassignmentOutcome.AED_MISMATCH
    assert rejected.changed_assignment is False

    _handle(service, _report(NEAREST, 1, now, "report-1"), now, fresh_helper)
    accepted = _handle(service, early, now, fresh_helper)
    assert accepted.outcome is ReassignmentOutcome.REASSIGNED
    assert accepted.assignment.aed_id == THIRD
    assert accepted.assignment.assignment_revision == 3

    replay = _handle(service, early, now, fresh_helper)
    assert replay.deduplicated is True
    assert replay.assignment.assignment_revision == 3
    assert service.store.get_assignment(INCIDENT_ID).assignment_revision == 3
