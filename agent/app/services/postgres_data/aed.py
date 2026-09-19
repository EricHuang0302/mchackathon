"""PostgreSQL repositories for AED datasets and revisioned assignments."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Jsonb

from data.aed.models import (
    AedRecord,
    AvailabilityStatus,
    GeoPoint,
    OpeningHours,
    OpeningWindow,
    SourceDescriptor,
)

from app.services.aed.assignment import (
    AedAssignment,
    AssignmentConflict,
    AssignmentState,
    AssignmentStatus,
    ReassignmentOutcome,
    ReassignmentResult,
)
from app.services.aed.availability import AvailabilityAssessment
from app.services.aed.candidates import AedCandidate, CandidateSearchResult
from app.services.aed.helpers import (
    HelperLocationStatus,
    HelperPosition,
    LocationFreshness,
)
from app.services.aed.retrieval import RetrievalAssumption, RetrievalEstimate
from app.services.aed.routing import (
    RouteEstimate,
    RouteEstimateConfig,
    RouteEstimateSource,
)
from app.services.incident.errors import INVALID_INPUT, UNAVAILABLE, ServiceError


class PostgresAedCatalogRepository:
    """Versioned AED imports with atomic active-version replacement."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def replace_dataset(
        self,
        descriptor: SourceDescriptor,
        records: Iterable[AedRecord],
        *,
        imported_at: datetime,
        expires_at: datetime | None = None,
    ) -> int:
        """Import and activate one complete version in a single transaction."""

        record_list = tuple(records)
        if not record_list:
            raise ServiceError(INVALID_INPUT, "empty_aed_dataset")
        for record in record_list:
            if (
                record.source_system != descriptor.source_system
                or record.dataset_version != descriptor.dataset_version
            ):
                raise ServiceError(
                    INVALID_INPUT,
                    "aed_record_dataset_mismatch",
                    detail={"stableId": record.stable_id},
                )
        try:
            with psycopg.connect(self.dsn) as connection:
                connection.execute(
                    "UPDATE aed_datasets SET active = false WHERE source_system = %s AND active",
                    (descriptor.source_system,),
                )
                dataset_id = connection.execute(
                    """
                    INSERT INTO aed_datasets (
                        source_system, source_url, dataset_version, retrieved_at,
                        imported_at, synthetic, license_note, active, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s)
                    ON CONFLICT (source_system, dataset_version) DO UPDATE SET
                        source_url = EXCLUDED.source_url,
                        retrieved_at = EXCLUDED.retrieved_at,
                        imported_at = EXCLUDED.imported_at,
                        synthetic = EXCLUDED.synthetic,
                        license_note = EXCLUDED.license_note,
                        active = true,
                        expires_at = EXCLUDED.expires_at
                    RETURNING dataset_id
                    """,
                    (
                        descriptor.source_system,
                        descriptor.source_url,
                        descriptor.dataset_version,
                        descriptor.retrieved_at,
                        imported_at,
                        descriptor.synthetic,
                        descriptor.license_note,
                        expires_at,
                    ),
                ).fetchone()[0]
                connection.execute(
                    "DELETE FROM aed_locations WHERE dataset_id = %s", (dataset_id,)
                )
                for record in record_list:
                    connection.execute(
                        """
                        INSERT INTO aed_locations (
                            dataset_id, stable_id, source_id, source_location_id,
                            source_system, name,
                            latitude, longitude, address, opening_hours, access_notes,
                            access_notes_known, source_url, source_updated_at,
                            ingested_at, dataset_version, data_quality_notes
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            dataset_id,
                            record.stable_id,
                            record.source_id,
                            record.source_location_id,
                            record.source_system,
                            record.name,
                            record.latitude,
                            record.longitude,
                            record.address,
                            Jsonb(_opening_hours_to_data(record.opening_hours)),
                            record.access_notes,
                            record.access_notes_known,
                            record.source_url,
                            record.source_updated_at,
                            record.ingested_at,
                            record.dataset_version,
                            Jsonb(list(record.data_quality_notes)),
                        ),
                    )
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        return len(record_list)

    def list_active(self, source_system: str | None = None) -> tuple[AedRecord, ...]:
        query = """
            SELECT l.stable_id, l.source_id, l.source_location_id,
                l.source_system, l.name,
                l.latitude, l.longitude, l.address, l.opening_hours,
                l.access_notes, l.access_notes_known, l.source_url,
                l.source_updated_at, l.ingested_at, l.dataset_version,
                l.data_quality_notes
            FROM aed_locations l
            JOIN aed_datasets d ON d.dataset_id = l.dataset_id
            WHERE d.active
        """
        params: tuple[Any, ...] = ()
        if source_system is not None:
            query += " AND d.source_system = %s"
            params = (source_system,)
        query += " ORDER BY l.stable_id"
        try:
            with psycopg.connect(self.dsn) as connection:
                rows = connection.execute(query, params).fetchall()
        except psycopg.Error as exc:
            raise ServiceError(
                UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__}
            ) from None
        return tuple(_aed_record_from_row(row) for row in rows)


class PostgresAssignmentStore:
    """Transactional compare-and-set storage for AED reassignment."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def read_state(self, incident_id: str) -> AssignmentState:
        try:
            with psycopg.connect(self.dsn) as connection:
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                assignment_row = connection.execute(
                    f"SELECT {_ASSIGNMENT_COLUMNS} FROM aed_assignments WHERE incident_id = %s",
                    (incident_id,),
                ).fetchone()
                exclusion_rows = connection.execute(
                    "SELECT aed_id FROM aed_assignment_exclusions WHERE incident_id = %s",
                    (incident_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise _db_error(exc) from None
        return AssignmentState(
            incident_id=incident_id,
            assignment=_assignment_from_row(assignment_row) if assignment_row else None,
            excluded_aed_ids=frozenset(row[0] for row in exclusion_rows),
        )

    def get_assignment(self, incident_id: str) -> AedAssignment | None:
        try:
            with psycopg.connect(self.dsn) as connection:
                row = connection.execute(
                    f"SELECT {_ASSIGNMENT_COLUMNS} FROM aed_assignments WHERE incident_id = %s",
                    (incident_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise _db_error(exc) from None
        return _assignment_from_row(row) if row else None

    def excluded_aed_ids(self, incident_id: str) -> frozenset[str]:
        try:
            with psycopg.connect(self.dsn) as connection:
                rows = connection.execute(
                    "SELECT aed_id FROM aed_assignment_exclusions WHERE incident_id = %s",
                    (incident_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise _db_error(exc) from None
        return frozenset(row[0] for row in rows)

    def get_report_result(
        self, incident_id: str, report_id: str
    ) -> ReassignmentResult | None:
        try:
            with psycopg.connect(self.dsn) as connection:
                row = connection.execute(
                    "SELECT result FROM aed_unavailability_reports WHERE incident_id = %s AND report_id = %s",
                    (incident_id, report_id),
                ).fetchone()
        except psycopg.Error as exc:
            raise _db_error(exc) from None
        return _result_from_data(row[0]) if row else None

    def commit_assignment(
        self,
        incident_id: str,
        *,
        expected_revision: int | None,
        assignment: AedAssignment,
        exclude_aed_id: str | None = None,
        report_id: str | None = None,
        result: ReassignmentResult | None = None,
    ) -> None:
        if (report_id is None) != (result is None):
            raise ValueError("report_id and result must be supplied together")
        if assignment.incident_id != incident_id:
            raise ValueError("assignment incident_id does not match")
        try:
            with psycopg.connect(self.dsn) as connection:
                incident_row = connection.execute(
                    "SELECT expires_at FROM incidents WHERE incident_id = %s FOR UPDATE",
                    (incident_id,),
                ).fetchone()
                if incident_row is None:
                    raise AssignmentConflict("incident_missing", incident_id)
                current = connection.execute(
                    "SELECT assignment_revision FROM aed_assignments WHERE incident_id = %s FOR UPDATE",
                    (incident_id,),
                ).fetchone()
                current_revision = current[0] if current else None
                if current_revision != expected_revision:
                    raise AssignmentConflict(
                        "revision_changed",
                        f"expected {expected_revision}, stored {current_revision}",
                    )
                if report_id is not None:
                    processed = connection.execute(
                        "SELECT 1 FROM aed_unavailability_reports WHERE incident_id = %s AND report_id = %s",
                        (incident_id, report_id),
                    ).fetchone()
                    if processed:
                        raise AssignmentConflict("report_already_processed", report_id)

                if exclude_aed_id is not None:
                    connection.execute(
                        """
                        INSERT INTO aed_assignment_exclusions (incident_id, aed_id, excluded_at)
                        VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                        """,
                        (incident_id, exclude_aed_id, assignment.assigned_at),
                    )
                connection.execute(
                    """
                    INSERT INTO aed_assignments (
                        incident_id, helper_id, aed_id, assignment_revision,
                        assigned_at, status, candidate, estimate, previous_aed_id, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (incident_id) DO UPDATE SET
                        helper_id = EXCLUDED.helper_id,
                        aed_id = EXCLUDED.aed_id,
                        assignment_revision = EXCLUDED.assignment_revision,
                        assigned_at = EXCLUDED.assigned_at,
                        status = EXCLUDED.status,
                        candidate = EXCLUDED.candidate,
                        estimate = EXCLUDED.estimate,
                        previous_aed_id = EXCLUDED.previous_aed_id,
                        expires_at = EXCLUDED.expires_at
                    """,
                    _assignment_values(assignment, incident_row[0]),
                )
                if report_id is not None and result is not None:
                    connection.execute(
                        """
                        INSERT INTO aed_unavailability_reports (
                            incident_id, report_id, result, expires_at
                        ) VALUES (%s, %s, %s, %s)
                        """,
                        (
                            incident_id,
                            report_id,
                            Jsonb(_result_to_data(result)),
                            incident_row[0],
                        ),
                    )
        except AssignmentConflict:
            raise
        except psycopg.Error as exc:
            raise _db_error(exc) from None

    def record_report_result(
        self, incident_id: str, report_id: str, result: ReassignmentResult
    ) -> ReassignmentResult:
        try:
            with psycopg.connect(self.dsn) as connection:
                row = connection.execute(
                    "SELECT expires_at FROM incidents WHERE incident_id = %s",
                    (incident_id,),
                ).fetchone()
                if row is None:
                    raise AssignmentConflict("incident_missing", incident_id)
                connection.execute(
                    """
                    INSERT INTO aed_unavailability_reports (
                        incident_id, report_id, result, expires_at
                    ) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                    """,
                    (incident_id, report_id, Jsonb(_result_to_data(result)), row[0]),
                )
                stored = connection.execute(
                    "SELECT result FROM aed_unavailability_reports WHERE incident_id = %s AND report_id = %s",
                    (incident_id, report_id),
                ).fetchone()[0]
        except AssignmentConflict:
            raise
        except psycopg.Error as exc:
            raise _db_error(exc) from None
        return _result_from_data(stored)


def _db_error(exc: psycopg.Error) -> ServiceError:
    return ServiceError(UNAVAILABLE, "postgres_unavailable", detail={"type": type(exc).__name__})


def _opening_hours_to_data(hours: OpeningHours) -> dict[str, Any]:
    return {
        "known": hours.known,
        "alwaysOpen": hours.always_open,
        "windows": [
            {
                "weekday": window.weekday,
                "startMinute": window.start_minute,
                "endMinute": window.end_minute,
            }
            for window in hours.windows
        ],
        "unknownWeekdays": list(hours.unknown_weekdays),
        "raw": hours.raw,
        "parseNote": hours.parse_note,
    }


def _opening_hours_from_data(data: dict[str, Any]) -> OpeningHours:
    return OpeningHours(
        known=data["known"],
        always_open=data.get("alwaysOpen", False),
        windows=tuple(
            OpeningWindow(
                weekday=value["weekday"],
                start_minute=value["startMinute"],
                end_minute=value["endMinute"],
            )
            for value in data.get("windows", ())
        ),
        unknown_weekdays=tuple(data.get("unknownWeekdays", ())),
        raw=data.get("raw"),
        parse_note=data.get("parseNote"),
    )


def _aed_record_from_row(row: tuple[Any, ...]) -> AedRecord:
    return AedRecord(
        stable_id=row[0],
        source_id=row[1],
        source_location_id=row[2],
        source_system=row[3],
        name=row[4],
        point=GeoPoint(row[5], row[6]),
        address=row[7],
        opening_hours=_opening_hours_from_data(row[8]),
        access_notes=row[9],
        access_notes_known=row[10],
        source_url=row[11],
        source_updated_at=row[12],
        ingested_at=row[13],
        dataset_version=row[14],
        data_quality_notes=tuple(row[15]),
    )


_ASSIGNMENT_COLUMNS = """
incident_id, helper_id, aed_id, assignment_revision, assigned_at, status,
candidate, estimate, previous_aed_id
"""


def _assignment_values(assignment: AedAssignment, expires_at: datetime) -> tuple[Any, ...]:
    return (
        assignment.incident_id,
        assignment.helper_id,
        assignment.aed_id,
        assignment.assignment_revision,
        assignment.assigned_at,
        assignment.status.value,
        Jsonb(_candidate_to_data(assignment.candidate)) if assignment.candidate else None,
        Jsonb(_estimate_to_data(assignment.estimate)) if assignment.estimate else None,
        assignment.previous_aed_id,
        expires_at,
    )


def _assignment_from_row(row: tuple[Any, ...]) -> AedAssignment:
    return AedAssignment(
        incident_id=row[0],
        helper_id=row[1],
        aed_id=row[2],
        assignment_revision=row[3],
        assigned_at=row[4],
        status=AssignmentStatus(row[5]),
        candidate=_candidate_from_data(row[6]) if row[6] else None,
        estimate=_estimate_from_data(row[7]) if row[7] else None,
        previous_aed_id=row[8],
    )


def _record_to_data(record: AedRecord) -> dict[str, Any]:
    return {
        "stableId": record.stable_id,
        "sourceId": record.source_id,
        "sourceLocationId": record.source_location_id,
        "sourceSystem": record.source_system,
        "name": record.name,
        "latitude": record.latitude,
        "longitude": record.longitude,
        "address": record.address,
        "openingHours": _opening_hours_to_data(record.opening_hours),
        "accessNotes": record.access_notes,
        "accessNotesKnown": record.access_notes_known,
        "sourceUrl": record.source_url,
        "sourceUpdatedAt": _time(record.source_updated_at),
        "ingestedAt": _time(record.ingested_at),
        "datasetVersion": record.dataset_version,
        "dataQualityNotes": list(record.data_quality_notes),
    }


def _record_from_data(data: dict[str, Any]) -> AedRecord:
    return AedRecord(
        stable_id=data["stableId"],
        source_id=data["sourceId"],
        source_location_id=data.get("sourceLocationId"),
        source_system=data["sourceSystem"],
        name=data["name"],
        point=GeoPoint(data["latitude"], data["longitude"]),
        address=data["address"],
        opening_hours=_opening_hours_from_data(data["openingHours"]),
        access_notes=data.get("accessNotes"),
        access_notes_known=data["accessNotesKnown"],
        source_url=data["sourceUrl"],
        source_updated_at=_datetime(data.get("sourceUpdatedAt")),
        ingested_at=_datetime(data["ingestedAt"]),
        dataset_version=data["datasetVersion"],
        data_quality_notes=tuple(data.get("dataQualityNotes", ())),
    )


def _candidate_to_data(candidate: AedCandidate) -> dict[str, Any]:
    availability = candidate.availability
    return {
        "record": _record_to_data(candidate.record),
        "straightLineMeters": candidate.straight_line_meters,
        "availability": {
            "status": availability.status.value,
            "reasonCode": availability.reason_code,
            "hoursKnown": availability.hours_known,
            "rawOpeningHours": availability.raw_opening_hours,
            "sourceUpdatedAt": _time(availability.source_updated_at),
            "datasetVersion": availability.dataset_version,
            "evaluatedAt": _time(availability.evaluated_at),
            "uncertainty": list(availability.uncertainty),
        },
    }


def _candidate_from_data(data: dict[str, Any]) -> AedCandidate:
    value = data["availability"]
    return AedCandidate(
        record=_record_from_data(data["record"]),
        straight_line_meters=data["straightLineMeters"],
        availability=AvailabilityAssessment(
            status=AvailabilityStatus(value["status"]),
            reason_code=value["reasonCode"],
            hours_known=value["hoursKnown"],
            raw_opening_hours=value.get("rawOpeningHours"),
            source_updated_at=_datetime(value.get("sourceUpdatedAt")),
            dataset_version=value["datasetVersion"],
            evaluated_at=_datetime(value["evaluatedAt"]),
            uncertainty=tuple(value.get("uncertainty", ())),
        ),
    )


def _point_to_data(point: GeoPoint) -> dict[str, float]:
    return {"latitude": point.latitude, "longitude": point.longitude}


def _point_from_data(data: dict[str, Any]) -> GeoPoint:
    return GeoPoint(data["latitude"], data["longitude"])


def _route_to_data(route: RouteEstimate) -> dict[str, Any]:
    return {
        "origin": _point_to_data(route.origin),
        "destination": _point_to_data(route.destination),
        "distanceMeters": route.distance_meters,
        "durationSeconds": route.duration_seconds,
        "source": route.source.value,
        "provider": route.provider,
        "computedAt": _time(route.computed_at),
        "uncertainty": list(route.uncertainty),
        "failureReason": route.failure_reason,
        "config": {
            "detourFactor": route.config.detour_factor,
            "walkingSpeedMps": route.config.walking_speed_mps,
            "freshAfterSeconds": route.config.fresh_after.total_seconds(),
            "staleAfterSeconds": route.config.stale_after.total_seconds(),
        },
    }


def _route_from_data(data: dict[str, Any]) -> RouteEstimate:
    config = data["config"]
    return RouteEstimate(
        origin=_point_from_data(data["origin"]),
        destination=_point_from_data(data["destination"]),
        distance_meters=data["distanceMeters"],
        duration_seconds=data["durationSeconds"],
        source=RouteEstimateSource(data["source"]),
        provider=data["provider"],
        computed_at=_datetime(data["computedAt"]),
        uncertainty=tuple(data.get("uncertainty", ())),
        failure_reason=data.get("failureReason"),
        config=RouteEstimateConfig(
            detour_factor=config["detourFactor"],
            walking_speed_mps=config["walkingSpeedMps"],
            fresh_after=timedelta(seconds=config["freshAfterSeconds"]),
            stale_after=timedelta(seconds=config["staleAfterSeconds"]),
        ),
    )


def _helper_status_to_data(status: HelperLocationStatus | None) -> dict[str, Any] | None:
    if status is None:
        return None
    position = status.position
    return {
        "helperId": status.helper_id,
        "position": None
        if position is None
        else {
            "helperId": position.helper_id,
            "point": _point_to_data(position.point),
            "reportedAt": _time(position.reported_at),
            "accuracyMeters": position.accuracy_meters,
            "pageVisible": position.page_visible,
        },
        "freshness": status.freshness.value,
        "ageSeconds": status.age_seconds,
        "evaluatedAt": _time(status.evaluated_at),
        "notes": list(status.notes),
    }


def _helper_status_from_data(data: dict[str, Any] | None) -> HelperLocationStatus | None:
    if data is None:
        return None
    position = data.get("position")
    return HelperLocationStatus(
        helper_id=data["helperId"],
        position=None
        if position is None
        else HelperPosition(
            helper_id=position["helperId"],
            point=_point_from_data(position["point"]),
            reported_at=_datetime(position["reportedAt"]),
            accuracy_meters=position.get("accuracyMeters"),
            page_visible=position.get("pageVisible", True),
        ),
        freshness=LocationFreshness(data["freshness"]),
        age_seconds=data.get("ageSeconds"),
        evaluated_at=_datetime(data["evaluatedAt"]),
        notes=tuple(data.get("notes", ())),
    )


def _estimate_to_data(estimate: RetrievalEstimate) -> dict[str, Any]:
    return {
        "helperId": estimate.helper_id,
        "aedId": estimate.aed_id,
        "outbound": _route_to_data(estimate.outbound),
        "retrievalAssumption": {
            "seconds": estimate.retrieval_assumption.seconds,
            "label": estimate.retrieval_assumption.label,
        },
        "returnLeg": _route_to_data(estimate.return_leg),
        "computedAt": _time(estimate.computed_at),
        "helperLocation": _helper_status_to_data(estimate.helper_location),
        "uncertainty": list(estimate.uncertainty),
    }


def _estimate_from_data(data: dict[str, Any]) -> RetrievalEstimate:
    assumption = data["retrievalAssumption"]
    return RetrievalEstimate(
        helper_id=data["helperId"],
        aed_id=data["aedId"],
        outbound=_route_from_data(data["outbound"]),
        retrieval_assumption=RetrievalAssumption(
            seconds=assumption["seconds"], label=assumption["label"]
        ),
        return_leg=_route_from_data(data["returnLeg"]),
        computed_at=_datetime(data["computedAt"]),
        helper_location=_helper_status_from_data(data.get("helperLocation")),
        uncertainty=tuple(data.get("uncertainty", ())),
    )


def _assignment_to_data(assignment: AedAssignment | None) -> dict[str, Any] | None:
    if assignment is None:
        return None
    return {
        "incidentId": assignment.incident_id,
        "helperId": assignment.helper_id,
        "aedId": assignment.aed_id,
        "assignmentRevision": assignment.assignment_revision,
        "assignedAt": _time(assignment.assigned_at),
        "status": assignment.status.value,
        "candidate": _candidate_to_data(assignment.candidate) if assignment.candidate else None,
        "estimate": _estimate_to_data(assignment.estimate) if assignment.estimate else None,
        "previousAedId": assignment.previous_aed_id,
    }


def _assignment_from_data(data: dict[str, Any] | None) -> AedAssignment | None:
    if data is None:
        return None
    return AedAssignment(
        incident_id=data["incidentId"],
        helper_id=data["helperId"],
        aed_id=data.get("aedId"),
        assignment_revision=data["assignmentRevision"],
        assigned_at=_datetime(data["assignedAt"]),
        status=AssignmentStatus(data["status"]),
        candidate=_candidate_from_data(data["candidate"]) if data.get("candidate") else None,
        estimate=_estimate_from_data(data["estimate"]) if data.get("estimate") else None,
        previous_aed_id=data.get("previousAedId"),
    )


def _search_to_data(search: CandidateSearchResult | None) -> dict[str, Any] | None:
    if search is None:
        return None
    return {
        "origin": _point_to_data(search.origin),
        "candidates": [_candidate_to_data(candidate) for candidate in search.candidates],
        "searchedRadiusMeters": search.searched_radius_meters,
        "radiusExpanded": search.radius_expanded,
        "examinedCount": search.examined_count,
        "excludedCount": search.excluded_count,
        "evaluatedAt": _time(search.evaluated_at),
    }


def _search_from_data(data: dict[str, Any] | None) -> CandidateSearchResult | None:
    if data is None:
        return None
    return CandidateSearchResult(
        origin=_point_from_data(data["origin"]),
        candidates=tuple(_candidate_from_data(value) for value in data["candidates"]),
        searched_radius_meters=data["searchedRadiusMeters"],
        radius_expanded=data["radiusExpanded"],
        examined_count=data["examinedCount"],
        excluded_count=data["excludedCount"],
        evaluated_at=_datetime(data["evaluatedAt"]),
    )


def _result_to_data(result: ReassignmentResult) -> dict[str, Any]:
    return {
        "outcome": result.outcome.value,
        "incidentId": result.incident_id,
        "assignment": _assignment_to_data(result.assignment),
        "excludedAedIds": list(result.excluded_aed_ids),
        "detail": result.detail,
        "reportId": result.report_id,
        "deduplicated": result.deduplicated,
        "search": _search_to_data(result.search),
    }


def _result_from_data(data: dict[str, Any]) -> ReassignmentResult:
    return ReassignmentResult(
        outcome=ReassignmentOutcome(data["outcome"]),
        incident_id=data["incidentId"],
        assignment=_assignment_from_data(data.get("assignment")),
        excluded_aed_ids=tuple(data.get("excludedAedIds", ())),
        detail=data.get("detail", ""),
        report_id=data.get("reportId"),
        deduplicated=data.get("deduplicated", False),
        search=_search_from_data(data.get("search")),
    )


def _time(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


__all__ = ["PostgresAedCatalogRepository", "PostgresAssignmentStore"]
