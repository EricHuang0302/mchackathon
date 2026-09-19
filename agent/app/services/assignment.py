"""AED assignment and unavailable-AED reassignment.

The service is idempotent and revision-aware:

* A replayed report identifier returns the stored result and changes nothing.
* A repeated report about an AED that is already excluded is acknowledged with
  the current assignment instead of producing a second one.
* A genuinely stale revision for a still-current AED is rejected.
* A successful report excludes that candidate for the incident and produces
  exactly one revised assignment.
* When nothing viable remains, the result says so instead of recycling a
  candidate that already failed.

Persistence lives behind :class:`AssignmentStore`; Firestore-backed storage
belongs to a different change. Nothing here claims an AED is physically
present or that a route estimate is measured.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Protocol

from data.aed.models import AedRecord, GeoPoint

from agent.app.services.candidates import (
    AedCandidate,
    CandidateSearchConfig,
    CandidateSearchResult,
    find_candidates,
)
from agent.app.services.helpers import (
    DEFAULT_HELPER_LOCATION_CONFIG,
    HelperLocationConfig,
    HelperLocationStatus,
)
from agent.app.services.retrieval import (
    DEFAULT_RETRIEVAL_ASSUMPTION,
    RetrievalAssumption,
    RetrievalEstimate,
    estimate_retrieval,
)
from agent.app.services.routing import (
    DEFAULT_ROUTE_ESTIMATE_CONFIG,
    RouteEstimateConfig,
    RouteProvider,
)


class AssignmentStatus(str, Enum):
    """Lifecycle of the incident's current AED assignment."""

    ASSIGNED = "assigned"
    NO_CANDIDATE = "no_candidate"


class ReassignmentOutcome(str, Enum):
    """Result of one assignment or reassignment attempt."""

    ASSIGNED = "assigned"
    REASSIGNED = "reassigned"
    DUPLICATE_REPORT = "duplicate_report"
    STALE_REVISION = "stale_revision"
    NOT_ASSIGNED = "not_assigned"
    AED_MISMATCH = "aed_mismatch"
    NO_CANDIDATE = "no_candidate"


@dataclass(frozen=True)
class AedAssignment:
    """The incident's current AED destination for one helper.

    ``previous_aed_id`` names the AED that the immediately preceding revision
    pointed at, so it is ``None`` for the first assignment and after an
    exhausted search.
    """

    incident_id: str
    helper_id: str
    aed_id: str | None
    assignment_revision: int
    assigned_at: datetime
    status: AssignmentStatus
    candidate: AedCandidate | None = None
    estimate: RetrievalEstimate | None = None
    previous_aed_id: str | None = None


@dataclass(frozen=True)
class UnavailabilityReport:
    """A helper report that the assigned AED could not be obtained."""

    report_id: str
    incident_id: str
    helper_id: str
    aed_id: str
    reason_code: str
    reported_at: datetime
    expected_assignment_revision: int


@dataclass(frozen=True)
class ReassignmentResult:
    """The outcome of one attempt, plus the assignment the helper should see."""

    outcome: ReassignmentOutcome
    incident_id: str
    assignment: AedAssignment | None
    excluded_aed_ids: tuple[str, ...]
    detail: str = ""
    report_id: str | None = None
    deduplicated: bool = False
    search: CandidateSearchResult | None = field(default=None, repr=False)

    @property
    def changed_assignment(self) -> bool:
        """Whether this attempt produced a new assignment revision."""

        return self.outcome in (ReassignmentOutcome.ASSIGNED, ReassignmentOutcome.REASSIGNED)


class AssignmentStore(Protocol):
    """Storage seam for assignments, exclusions, and processed reports."""

    def get_assignment(self, incident_id: str) -> AedAssignment | None: ...

    def put_assignment(self, assignment: AedAssignment) -> None: ...

    def excluded_aed_ids(self, incident_id: str) -> frozenset[str]: ...

    def add_exclusion(self, incident_id: str, aed_id: str) -> None: ...

    def get_report_result(self, incident_id: str, report_id: str) -> ReassignmentResult | None: ...

    def record_report_result(
        self, incident_id: str, report_id: str, result: ReassignmentResult
    ) -> None: ...


class InMemoryAssignmentStore:
    """Process-local store used by tests and offline demonstrations.

    This is an explicit stand-in for incident persistence, not a datastore.
    """

    def __init__(self) -> None:
        self._assignments: dict[str, AedAssignment] = {}
        self._exclusions: dict[str, set[str]] = {}
        self._reports: dict[tuple[str, str], ReassignmentResult] = {}

    def get_assignment(self, incident_id: str) -> AedAssignment | None:
        return self._assignments.get(incident_id)

    def put_assignment(self, assignment: AedAssignment) -> None:
        self._assignments[assignment.incident_id] = assignment

    def excluded_aed_ids(self, incident_id: str) -> frozenset[str]:
        return frozenset(self._exclusions.get(incident_id, set()))

    def add_exclusion(self, incident_id: str, aed_id: str) -> None:
        self._exclusions.setdefault(incident_id, set()).add(aed_id)

    def get_report_result(self, incident_id: str, report_id: str) -> ReassignmentResult | None:
        return self._reports.get((incident_id, report_id))

    def record_report_result(
        self, incident_id: str, report_id: str, result: ReassignmentResult
    ) -> None:
        self._reports[(incident_id, report_id)] = result


@dataclass
class AedAssignmentService:
    """Selects AED destinations and handles unavailable-AED reports."""

    records: Sequence[AedRecord]
    route_provider: RouteProvider
    store: AssignmentStore = field(default_factory=InMemoryAssignmentStore)
    search_config: CandidateSearchConfig = field(default_factory=CandidateSearchConfig)
    route_config: RouteEstimateConfig = DEFAULT_ROUTE_ESTIMATE_CONFIG
    location_config: HelperLocationConfig = DEFAULT_HELPER_LOCATION_CONFIG
    retrieval_assumption: RetrievalAssumption = DEFAULT_RETRIEVAL_ASSUMPTION

    def assign(
        self,
        *,
        incident_id: str,
        helper_location: HelperLocationStatus,
        patient_point: GeoPoint,
        now: datetime,
    ) -> ReassignmentResult:
        """Create the first assignment for an incident, or report none exists."""

        existing = self.store.get_assignment(incident_id)
        if existing is not None and existing.status is AssignmentStatus.ASSIGNED:
            return ReassignmentResult(
                outcome=ReassignmentOutcome.DUPLICATE_REPORT,
                incident_id=incident_id,
                assignment=existing,
                excluded_aed_ids=tuple(sorted(self.store.excluded_aed_ids(incident_id))),
                detail="incident already has a current assignment",
                deduplicated=True,
            )

        # A retry after an exhausted search must move the revision forward
        # rather than restart it, so acknowledgements stay comparable.
        revision = 1 if existing is None else existing.assignment_revision + 1
        return self._select_and_store(
            incident_id=incident_id,
            helper_location=helper_location,
            patient_point=patient_point,
            now=now,
            revision=revision,
            # previous_aed_id always names the AED the preceding revision
            # pointed at, which is None after an exhausted search.
            previous_aed_id=None if existing is None else existing.aed_id,
            outcome_on_success=ReassignmentOutcome.ASSIGNED,
            report_id=None,
        )

    def report_unavailable(
        self,
        report: UnavailabilityReport,
        *,
        helper_location: HelperLocationStatus,
        patient_point: GeoPoint,
        now: datetime,
    ) -> ReassignmentResult:
        """Handle an unavailable-AED report and return the revised assignment."""

        incident_id = report.incident_id
        excluded = self.store.excluded_aed_ids(incident_id)

        # 1. Replay of the same report identifier: return the stored result.
        cached = self.store.get_report_result(incident_id, report.report_id)
        if cached is not None:
            return replace(cached, deduplicated=True)

        current = self.store.get_assignment(incident_id)

        # 2. A fresh report about an already-excluded AED is a repeat, even if
        #    it carries an older assignment revision. Acknowledge it with the
        #    current assignment rather than rejecting or reassigning again.
        if report.aed_id in excluded:
            result = ReassignmentResult(
                outcome=ReassignmentOutcome.DUPLICATE_REPORT,
                incident_id=incident_id,
                assignment=current,
                excluded_aed_ids=tuple(sorted(excluded)),
                detail=f"{report.aed_id} was already excluded for this incident",
                report_id=report.report_id,
                deduplicated=True,
            )
            self.store.record_report_result(incident_id, report.report_id, result)
            return result

        if current is None or current.status is not AssignmentStatus.ASSIGNED:
            return ReassignmentResult(
                outcome=ReassignmentOutcome.NOT_ASSIGNED,
                incident_id=incident_id,
                assignment=current,
                excluded_aed_ids=tuple(sorted(excluded)),
                detail="no current assignment to invalidate",
                report_id=report.report_id,
            )

        if current.aed_id != report.aed_id:
            return ReassignmentResult(
                outcome=ReassignmentOutcome.AED_MISMATCH,
                incident_id=incident_id,
                assignment=current,
                excluded_aed_ids=tuple(sorted(excluded)),
                detail=(
                    f"report targets {report.aed_id} but the current assignment is "
                    f"{current.aed_id}"
                ),
                report_id=report.report_id,
            )

        # 3. Only now does the revision gate apply, so a duplicate carrying an
        #    old revision is acknowledged above instead of being rejected here.
        if report.expected_assignment_revision != current.assignment_revision:
            return ReassignmentResult(
                outcome=ReassignmentOutcome.STALE_REVISION,
                incident_id=incident_id,
                assignment=current,
                excluded_aed_ids=tuple(sorted(excluded)),
                detail=(
                    f"expected revision {report.expected_assignment_revision}, "
                    f"current revision {current.assignment_revision}"
                ),
                report_id=report.report_id,
            )

        self.store.add_exclusion(incident_id, report.aed_id)
        result = self._select_and_store(
            incident_id=incident_id,
            helper_location=helper_location,
            patient_point=patient_point,
            now=now,
            revision=current.assignment_revision + 1,
            previous_aed_id=current.aed_id,
            outcome_on_success=ReassignmentOutcome.REASSIGNED,
            report_id=report.report_id,
            helper_id=current.helper_id,
        )
        self.store.record_report_result(incident_id, report.report_id, result)
        return result

    def _select_and_store(
        self,
        *,
        incident_id: str,
        helper_location: HelperLocationStatus,
        patient_point: GeoPoint,
        now: datetime,
        revision: int,
        previous_aed_id: str | None,
        outcome_on_success: ReassignmentOutcome,
        report_id: str | None,
        helper_id: str | None = None,
    ) -> ReassignmentResult:
        excluded = self.store.excluded_aed_ids(incident_id)
        search = find_candidates(
            self.records,
            patient_point,
            at=now,
            config=self.search_config,
            excluded_ids=excluded,
        )
        candidate = _first_dispatchable(search.candidates)
        resolved_helper_id = helper_id or helper_location.helper_id

        if candidate is None:
            assignment = AedAssignment(
                incident_id=incident_id,
                helper_id=resolved_helper_id,
                aed_id=None,
                assignment_revision=revision,
                assigned_at=now,
                status=AssignmentStatus.NO_CANDIDATE,
                previous_aed_id=previous_aed_id,
            )
            self.store.put_assignment(assignment)
            return ReassignmentResult(
                outcome=ReassignmentOutcome.NO_CANDIDATE,
                incident_id=incident_id,
                assignment=assignment,
                excluded_aed_ids=tuple(sorted(excluded)),
                detail=(
                    "no accessible AED candidate is known; previously reported "
                    "candidates are not offered again"
                ),
                report_id=report_id,
                search=search,
            )

        estimate = estimate_retrieval(
            self.route_provider,
            helper_location=helper_location,
            aed_id=candidate.stable_id,
            aed_point=candidate.record.point,
            patient_point=patient_point,
            now=now,
            route_config=self.route_config,
            location_config=self.location_config,
            retrieval_assumption=self.retrieval_assumption,
        )
        assignment = AedAssignment(
            incident_id=incident_id,
            helper_id=resolved_helper_id,
            aed_id=candidate.stable_id,
            assignment_revision=revision,
            assigned_at=now,
            status=AssignmentStatus.ASSIGNED,
            candidate=candidate,
            estimate=estimate,
            previous_aed_id=previous_aed_id,
        )
        self.store.put_assignment(assignment)
        return ReassignmentResult(
            outcome=outcome_on_success,
            incident_id=incident_id,
            assignment=assignment,
            excluded_aed_ids=tuple(sorted(excluded)),
            detail=f"selected {candidate.stable_id} at revision {revision}",
            report_id=report_id,
            search=search,
        )


def _first_dispatchable(candidates: Iterable[AedCandidate]) -> AedCandidate | None:
    """The best-ranked candidate that is not published as closed."""

    for candidate in candidates:
        if candidate.is_dispatchable:
            return candidate
    return None
