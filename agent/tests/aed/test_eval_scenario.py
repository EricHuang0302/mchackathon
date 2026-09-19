"""Drives the synthetic inaccessible-AED evaluation scenario end to end.

The scenario file under ``eval/scenarios/`` is data only; this test is the
runner for it. Everything it contains is synthetic.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

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

SCENARIO_PATH = (
    Path(__file__).resolve().parents[3]
    / "eval"
    / "scenarios"
    / "inaccessible_aed_reassignment.json"
)


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


@pytest.fixture(scope="module")
def scenario() -> dict:
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


def test_scenario_file_is_labeled_synthetic(scenario):
    assert "Synthetic evaluation data" in scenario["note"]


def test_scenario_ingestion_matches_expectations(scenario):
    now = _parse(scenario["now_utc"])
    descriptor = SourceDescriptor(
        source_system=scenario["source_system"],
        source_url=scenario["source_url"],
        dataset_version=scenario["dataset_version"],
        retrieved_at=now,
        synthetic=True,
    )
    source = JsonFileSource(
        path=SCENARIO_PATH, _descriptor=descriptor, records_key="aeds"
    )

    result = ingest(source, ingested_at=now)
    expected = scenario["expected_ingestion"]

    assert result.record_count == expected["record_count"]
    assert [issue.reason_code for issue in result.rejections] == expected[
        "rejection_reason_codes"
    ]
    unknown_hours = [
        record.stable_id for record in result.records if not record.opening_hours.known
    ]
    assert unknown_hours == expected["unknown_hours_stable_ids"]


def test_inaccessible_aed_scenario_produces_one_revised_assignment(scenario):
    now = _parse(scenario["now_utc"])
    descriptor = SourceDescriptor(
        source_system=scenario["source_system"],
        source_url=scenario["source_url"],
        dataset_version=scenario["dataset_version"],
        retrieved_at=now,
        synthetic=True,
    )
    records = ingest(
        JsonFileSource(path=SCENARIO_PATH, _descriptor=descriptor, records_key="aeds"),
        ingested_at=now,
    ).records

    patient = GeoPoint(
        latitude=scenario["patient"]["latitude"],
        longitude=scenario["patient"]["longitude"],
    )
    reported = scenario["helper_position"]
    helper_location = evaluate_helper_location(
        HelperPosition(
            helper_id=scenario["helper_id"],
            point=GeoPoint(
                latitude=reported["latitude"], longitude=reported["longitude"]
            ),
            reported_at=_parse(reported["reported_at_utc"]),
            accuracy_meters=reported["accuracy_meters"],
            page_visible=reported["page_visible"],
        ),
        now=now,
    )

    service = AedAssignmentService(
        records=records,
        route_provider=DeterministicFakeRouteProvider(),
        store=InMemoryAssignmentStore(),
        search_config=CandidateSearchConfig(
            radius_meters=scenario["search"]["radius_meters"],
            limit=scenario["search"]["limit"],
        ),
    )

    incident_id = scenario["incident_id"]
    for index, step in enumerate(scenario["steps"]):
        if step["action"] == "assign":
            result = service.assign(
                incident_id=incident_id,
                helper_location=helper_location,
                patient_point=patient,
                now=now,
            )
        else:
            result = service.report_unavailable(
                UnavailabilityReport(
                    report_id=step["report_id"],
                    incident_id=incident_id,
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

        expected = step["expect"]
        context = f"step {index} ({step['action']})"
        assert result.outcome.value == expected["outcome"], context
        assert result.assignment is not None, context
        assert result.assignment.aed_id == expected["aed_id"], context
        assert result.assignment.assignment_revision == expected[
            "assignment_revision"
        ], context
        if "deduplicated" in expected:
            assert result.deduplicated == expected["deduplicated"], context
        if "availability_status" in expected:
            assert result.assignment.candidate is not None, context
            assert (
                result.assignment.candidate.availability.status.value
                == expected["availability_status"]
            ), context

    assert sorted(service.store.excluded_aed_ids(incident_id)) == scenario[
        "expected_final_excluded_aed_ids"
    ]
