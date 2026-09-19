"""Synthetic AED assignment followed by an inaccessible-device reassignment."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from data.aed.models import GeoPoint, SourceDescriptor
from data.aed.pipeline import ingest
from data.aed.sources import JsonFileSource

from app.services.aed.assignment import (
    AedAssignmentService,
    InMemoryAssignmentStore,
    UnavailabilityReport,
)
from app.services.aed.candidates import CandidateSearchConfig
from app.services.aed.helpers import HelperPosition, evaluate_helper_location
from app.services.aed.routing import DeterministicFakeRouteProvider

NAME = "inaccessible_aed_reassignment"
DESCRIPTION = "Reassign an AED after a runner reports that it cannot be obtained."
SCENARIO_PATH = Path(__file__).with_suffix(".json")


def run() -> dict[str, object]:
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    now = _parse(scenario["now_utc"])
    descriptor = SourceDescriptor(
        source_system=scenario["source_system"],
        source_url=scenario["source_url"],
        dataset_version=scenario["dataset_version"],
        retrieved_at=now,
        synthetic=True,
    )
    ingestion = ingest(
        JsonFileSource(
            path=SCENARIO_PATH,
            _descriptor=descriptor,
            records_key="aeds",
        ),
        ingested_at=now,
    )
    patient = GeoPoint(
        latitude=scenario["patient"]["latitude"],
        longitude=scenario["patient"]["longitude"],
    )
    reported = scenario["helper_position"]
    helper_location = evaluate_helper_location(
        HelperPosition(
            helper_id=scenario["helper_id"],
            point=GeoPoint(
                latitude=reported["latitude"],
                longitude=reported["longitude"],
            ),
            reported_at=_parse(reported["reported_at_utc"]),
            accuracy_meters=reported["accuracy_meters"],
            page_visible=reported["page_visible"],
        ),
        now=now,
    )
    service = AedAssignmentService(
        records=ingestion.records,
        route_provider=DeterministicFakeRouteProvider(),
        store=InMemoryAssignmentStore(),
        search_config=CandidateSearchConfig(
            radius_meters=scenario["search"]["radius_meters"],
            limit=scenario["search"]["limit"],
        ),
    )

    steps: list[dict[str, object]] = []
    for step in scenario["steps"]:
        if step["action"] == "assign":
            result = service.assign(
                incident_id=scenario["incident_id"],
                helper_location=helper_location,
                patient_point=patient,
                now=now,
            )
        else:
            result = service.report_unavailable(
                UnavailabilityReport(
                    report_id=step["report_id"],
                    incident_id=scenario["incident_id"],
                    helper_id=scenario["helper_id"],
                    aed_id=step["aed_id"],
                    reason_code=step["reason_code"],
                    reported_at=now,
                    expected_assignment_revision=step["expected_assignment_revision"],
                ),
                helper_location=helper_location,
                patient_point=patient,
                now=now,
            )
        assignment = result.assignment
        steps.append(
            {
                "action": step["action"],
                "outcome": result.outcome.value,
                "aedId": assignment.aed_id if assignment else None,
                "assignmentRevision": (
                    assignment.assignment_revision if assignment else None
                ),
                "deduplicated": result.deduplicated,
            }
        )

    return {
        "description": DESCRIPTION,
        "synthetic": True,
        "ingestion": {
            "rowsRead": ingestion.rows_read,
            "recordCount": ingestion.record_count,
            "rejectionReasonCodes": [
                rejection.reason_code for rejection in ingestion.rejections
            ],
        },
        "steps": steps,
        "excludedAedIds": sorted(
            service.store.excluded_aed_ids(scenario["incident_id"])
        ),
    }


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
