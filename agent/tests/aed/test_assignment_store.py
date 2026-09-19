"""Atomic compare-and-set behavior of the assignment store seam.

The store is the concurrency boundary: two reports that read the same
assignment revision must not both advance it. These tests exercise the
compare-and-set directly, then end to end through concurrent threads.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.aed.assignment import (
    AedAssignment,
    AedAssignmentService,
    AssignmentConflict,
    AssignmentStatus,
    InMemoryAssignmentStore,
    ReassignmentOutcome,
    ReassignmentResult,
    UnavailabilityReport,
)
from app.services.aed.candidates import CandidateSearchConfig
from app.services.aed.routing import DeterministicFakeRouteProvider
from .conftest import PATIENT_POINT, make_record

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
    ]


def _assignment(now, *, revision: int, aed_id: str | None = NEAREST) -> AedAssignment:
    return AedAssignment(
        incident_id=INCIDENT_ID,
        helper_id=HELPER_ID,
        aed_id=aed_id,
        assignment_revision=revision,
        assigned_at=now,
        status=AssignmentStatus.ASSIGNED if aed_id else AssignmentStatus.NO_CANDIDATE,
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


class _GatedStore(InMemoryAssignmentStore):
    """Forces a deterministic read-read-commit-commit interleaving.

    The first ``parties`` calls to ``read_state`` block until all of them have
    arrived, so every gated caller plans against the same revision. Later
    reads (including conflict retries) pass straight through.
    """

    def __init__(self, parties: int) -> None:
        super().__init__()
        self._barrier = threading.Barrier(parties)
        self._gate_lock = threading.Lock()
        self._gate_uses = 0

    def arm(self, uses: int) -> None:
        with self._gate_lock:
            self._gate_uses = uses

    def read_state(self, incident_id: str):
        state = super().read_state(incident_id)
        with self._gate_lock:
            gated = self._gate_uses > 0
            if gated:
                self._gate_uses -= 1
        if gated:
            try:
                self._barrier.wait(timeout=10)
            except threading.BrokenBarrierError:  # pragma: no cover - safety valve
                pass
        return state


def test_commit_rejects_a_stale_expected_revision(now):
    store = InMemoryAssignmentStore()
    store.commit_assignment(
        INCIDENT_ID, expected_revision=None, assignment=_assignment(now, revision=1)
    )

    with pytest.raises(AssignmentConflict) as excinfo:
        store.commit_assignment(
            INCIDENT_ID,
            expected_revision=None,
            assignment=_assignment(now, revision=2, aed_id=SECOND),
        )

    assert excinfo.value.reason_code == "revision_changed"
    assert store.get_assignment(INCIDENT_ID).assignment_revision == 1


def test_commit_rejects_an_already_processed_report_id(now):
    store = InMemoryAssignmentStore()
    store.commit_assignment(
        INCIDENT_ID, expected_revision=None, assignment=_assignment(now, revision=1)
    )
    first = _assignment(now, revision=2, aed_id=SECOND)
    first_result = ReassignmentResult(
        outcome=ReassignmentOutcome.REASSIGNED,
        incident_id=INCIDENT_ID,
        assignment=first,
        excluded_aed_ids=(NEAREST,),
        report_id="report-1",
    )
    store.commit_assignment(
        INCIDENT_ID,
        expected_revision=1,
        assignment=first,
        exclude_aed_id=NEAREST,
        report_id="report-1",
        result=first_result,
    )

    with pytest.raises(AssignmentConflict) as excinfo:
        store.commit_assignment(
            INCIDENT_ID,
            expected_revision=2,
            assignment=_assignment(now, revision=3, aed_id=THIRD),
            report_id="report-1",
            result=first_result,
        )

    assert excinfo.value.reason_code == "report_already_processed"
    assert store.get_assignment(INCIDENT_ID).assignment_revision == 2


def test_failed_commit_applies_no_part_of_the_write(now):
    store = InMemoryAssignmentStore()
    store.commit_assignment(
        INCIDENT_ID, expected_revision=None, assignment=_assignment(now, revision=1)
    )

    failed_assignment = _assignment(now, revision=100, aed_id=SECOND)
    failed_result = ReassignmentResult(
        outcome=ReassignmentOutcome.REASSIGNED,
        incident_id=INCIDENT_ID,
        assignment=failed_assignment,
        excluded_aed_ids=(NEAREST,),
        report_id="report-1",
    )
    with pytest.raises(AssignmentConflict):
        store.commit_assignment(
            INCIDENT_ID,
            expected_revision=99,
            assignment=failed_assignment,
            exclude_aed_id=NEAREST,
            report_id="report-1",
            result=failed_result,
        )

    assert store.excluded_aed_ids(INCIDENT_ID) == frozenset()
    assert store.get_report_result(INCIDENT_ID, "report-1") is None
    assert store.get_assignment(INCIDENT_ID).assignment_revision == 1


def test_record_report_result_keeps_the_first_write(now):
    store = InMemoryAssignmentStore()

    first = ReassignmentResult(
        outcome=ReassignmentOutcome.DUPLICATE_REPORT,
        incident_id=INCIDENT_ID,
        assignment=None,
        excluded_aed_ids=(),
        detail="first",
    )
    second = ReassignmentResult(
        outcome=ReassignmentOutcome.STALE_REVISION,
        incident_id=INCIDENT_ID,
        assignment=None,
        excluded_aed_ids=(),
        detail="second",
    )

    assert store.record_report_result(INCIDENT_ID, "r", first) is first
    assert store.record_report_result(INCIDENT_ID, "r", second) is first


def test_commit_requires_report_id_and_result_together(now):
    store = InMemoryAssignmentStore()

    with pytest.raises(ValueError, match="supplied together"):
        store.commit_assignment(
            INCIDENT_ID,
            expected_revision=None,
            assignment=_assignment(now, revision=1),
            report_id="report-without-result",
        )


def test_concurrent_distinct_reports_produce_exactly_one_reassignment(
    now, fresh_helper
):
    """Two helpers report the same AED at the same revision simultaneously."""

    store = _GatedStore(parties=2)
    service = AedAssignmentService(
        records=_records(),
        route_provider=DeterministicFakeRouteProvider(),
        store=store,
        search_config=CandidateSearchConfig(radius_meters=1_000.0, limit=10),
    )
    service.assign(
        incident_id=INCIDENT_ID,
        helper_location=fresh_helper,
        patient_point=PATIENT_POINT,
        now=now,
    )
    store.arm(uses=2)

    def submit(report_id: str):
        return service.report_unavailable(
            _report(NEAREST, 1, now, report_id),
            helper_location=fresh_helper,
            patient_point=PATIENT_POINT,
            now=now,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ["report-a", "report-b"]))

    outcomes = sorted(result.outcome for result in results)
    assert outcomes.count(ReassignmentOutcome.REASSIGNED) == 1
    loser = next(r for r in results if r.outcome is not ReassignmentOutcome.REASSIGNED)
    assert loser.outcome in (
        ReassignmentOutcome.DUPLICATE_REPORT,
        ReassignmentOutcome.STALE_REVISION,
        ReassignmentOutcome.CONFLICT,
    )
    assert loser.changed_assignment is False

    # Exactly one revision was created, and both helpers see the same one.
    stored = store.get_assignment(INCIDENT_ID)
    assert stored.assignment_revision == 2
    assert stored.aed_id == SECOND
    assert store.excluded_aed_ids(INCIDENT_ID) == frozenset({NEAREST})
    assert {result.assignment.assignment_revision for result in results} == {2}


def test_concurrent_replays_of_one_report_id_produce_one_reassignment(
    now, fresh_helper
):
    store = _GatedStore(parties=2)
    service = AedAssignmentService(
        records=_records(),
        route_provider=DeterministicFakeRouteProvider(),
        store=store,
        search_config=CandidateSearchConfig(radius_meters=1_000.0, limit=10),
    )
    service.assign(
        incident_id=INCIDENT_ID,
        helper_location=fresh_helper,
        patient_point=PATIENT_POINT,
        now=now,
    )
    store.arm(uses=2)
    report = _report(NEAREST, 1, now, "report-same")

    def submit(_):
        return service.report_unavailable(
            report,
            helper_location=fresh_helper,
            patient_point=PATIENT_POINT,
            now=now,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))

    assert store.get_assignment(INCIDENT_ID).assignment_revision == 2
    assert {result.assignment.assignment_revision for result in results} == {2}
    assert {result.assignment.aed_id for result in results} == {SECOND}


def test_concurrent_initial_assignments_produce_one_revision(now, fresh_helper):
    store = _GatedStore(parties=2)
    service = AedAssignmentService(
        records=_records(),
        route_provider=DeterministicFakeRouteProvider(),
        store=store,
        search_config=CandidateSearchConfig(radius_meters=1_000.0, limit=10),
    )
    store.arm(uses=2)

    def submit(_):
        return service.assign(
            incident_id=INCIDENT_ID,
            helper_location=fresh_helper,
            patient_point=PATIENT_POINT,
            now=now,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))

    assert store.get_assignment(INCIDENT_ID).assignment_revision == 1
    assert [result.outcome for result in results].count(
        ReassignmentOutcome.ASSIGNED
    ) == 1
    assert {result.assignment.assignment_revision for result in results} == {1}


def test_store_stays_consistent_under_many_concurrent_reports(now, fresh_helper):
    """A burst of distinct report IDs never creates more than one revision."""

    store = InMemoryAssignmentStore()
    service = AedAssignmentService(
        records=_records(),
        route_provider=DeterministicFakeRouteProvider(),
        store=store,
        search_config=CandidateSearchConfig(radius_meters=1_000.0, limit=10),
    )
    service.assign(
        incident_id=INCIDENT_ID,
        helper_location=fresh_helper,
        patient_point=PATIENT_POINT,
        now=now,
    )

    def submit(index: int):
        return service.report_unavailable(
            _report(NEAREST, 1, now, f"report-{index}"),
            helper_location=fresh_helper,
            patient_point=PATIENT_POINT,
            now=now,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(24)))

    reassigned = [r for r in results if r.outcome is ReassignmentOutcome.REASSIGNED]
    assert len(reassigned) == 1
    assert store.get_assignment(INCIDENT_ID).assignment_revision == 2
    assert store.excluded_aed_ids(INCIDENT_ID) == frozenset({NEAREST})
    assert all(not r.changed_assignment for r in results if r not in reassigned)
