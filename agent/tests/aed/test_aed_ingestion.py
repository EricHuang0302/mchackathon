"""Ingestion and normalization of local synthetic AED exports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from data.aed.hours import parse_opening_hours
from data.aed.pipeline import IngestionResult, ingest, ingest_with_fallback
from data.aed.region import TAIWAN_REGION
from data.aed.sources import (
    SYNTHETIC_DESCRIPTOR,
    CsvFileSource,
    SourceReadError,
    synthetic_csv_source,
    synthetic_json_source,
    synthetic_malformed_csv_source,
)

INGESTED_AT = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)


def _reasons(issues) -> list[str]:
    return [issue.reason_code for issue in issues]


def test_synthetic_fixture_is_labeled_as_synthetic():
    assert SYNTHETIC_DESCRIPTOR.synthetic is True
    assert "not derived from a real AED location" in SYNTHETIC_DESCRIPTOR.license_note


def test_csv_source_normalizes_every_required_field():
    result = ingest(synthetic_csv_source(), ingested_at=INGESTED_AT)

    assert result.record_count == 6
    assert result.rejections == ()

    record = result.by_stable_id()["synthetic-demo:syn-002"]
    assert record.source_id == "SYN-002"
    assert record.source_system == "synthetic-demo"
    assert TAIWAN_REGION.contains(record.point)
    assert record.address.startswith("12 Example Lane")
    assert record.access_notes_known is True
    assert record.source_url == SYNTHETIC_DESCRIPTOR.source_url
    assert record.source_updated_at == datetime(2026, 8, 15, tzinfo=timezone.utc)
    assert record.ingested_at == INGESTED_AT
    assert record.dataset_version == "synthetic-2026-09-01"
    assert record.opening_hours.known is True
    assert len(record.opening_hours.windows) == 6


def test_json_source_produces_the_same_records_as_the_csv_source():
    from_csv = ingest(synthetic_csv_source(), ingested_at=INGESTED_AT)
    from_json = ingest(synthetic_json_source(), ingested_at=INGESTED_AT)

    assert from_csv.records == from_json.records


def test_stable_ids_are_deterministic_across_runs():
    first = ingest(synthetic_csv_source(), ingested_at=INGESTED_AT)
    second = ingest(synthetic_csv_source(), ingested_at=INGESTED_AT)

    assert [record.stable_id for record in first.records] == [
        record.stable_id for record in second.records
    ]


def test_malformed_source_rows_are_rejected_with_reason_codes():
    """Scenario: malformed source rows."""

    result = ingest(synthetic_malformed_csv_source(), ingested_at=INGESTED_AT)
    reasons = _reasons(result.rejections)

    assert "missing_source_id" in reasons
    assert "invalid_coordinates" in reasons
    assert "coordinates_out_of_region" in reasons
    assert "missing_address" in reasons
    assert "duplicate_source_id" in reasons
    # Only the valid rows survive.
    assert {record.source_id for record in result.records} == {
        "SYN-010",
        "SYN-014",
        "SYN-015",
    }


def test_duplicate_source_id_keeps_the_more_recently_updated_record():
    result = ingest(synthetic_malformed_csv_source(), ingested_at=INGESTED_AT)

    kept = result.by_stable_id()["synthetic-demo:syn-010"]
    assert kept.source_updated_at == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert kept.name == "Synthetic Duplicate Newer AED"


def test_missing_access_data_keeps_the_record_and_flags_it_unknown():
    """Scenario: missing access data stays unknown instead of being dropped."""

    result = ingest(synthetic_malformed_csv_source(), ingested_at=INGESTED_AT)

    record = result.by_stable_id()["synthetic-demo:syn-014"]
    assert record.access_notes is None
    assert record.access_notes_known is False
    assert record.opening_hours.known is False
    assert record.source_updated_at is None
    assert set(record.data_quality_notes) == {
        "unknown_opening_hours",
        "missing_access_notes",
        "missing_source_update_time",
    }
    row_reasons = _reasons(
        [warning for warning in result.warnings if warning.source_id == "SYN-014"]
    )
    assert set(row_reasons) == {
        "unknown_opening_hours",
        "missing_access_notes",
        "missing_source_update_time",
    }


def test_ambiguous_opening_hours_stay_unknown_with_the_raw_text_preserved():
    result = ingest(synthetic_malformed_csv_source(), ingested_at=INGESTED_AT)

    record = result.by_stable_id()["synthetic-demo:syn-015"]
    assert record.opening_hours.known is False
    assert record.opening_hours.raw == "office hours only"
    assert record.opening_hours.parse_note is not None


@pytest.mark.parametrize(
    ("raw", "known", "always_open"),
    [
        ("24/7", True, True),
        ("", False, False),
        ("unknown", False, False),
        ("Mon-Fri 08:00-18:00", True, False),
        ("sometimes", False, False),
        ("Mon 25:00-26:00", False, False),
        ("Mon 08:00-08:00", False, False),
        ("Mon 08:00-24:30", False, False),
        ("Mon 00:00-24:00", True, False),
    ],
)
def test_opening_hours_parser_never_guesses(raw, known, always_open):
    hours = parse_opening_hours(raw)

    assert hours.known is known
    assert hours.always_open is always_open


def test_overnight_window_extends_past_midnight():
    hours = parse_opening_hours("Mon 22:00-02:00")

    assert hours.known is True
    window = hours.windows[0]
    assert window.weekday == 0
    assert window.start_minute == 22 * 60
    assert window.end_minute == 26 * 60


def test_missing_mapped_column_raises_a_source_read_error(tmp_path: Path):
    path = tmp_path / "broken.csv"
    path.write_text("source_id,name\nSYN-900,Synthetic\n", encoding="utf-8")
    source = CsvFileSource(path=path, _descriptor=SYNTHETIC_DESCRIPTOR)

    with pytest.raises(SourceReadError):
        list(source.rows())


def test_failed_import_retains_the_last_valid_dataset(tmp_path: Path):
    previous = ingest(synthetic_csv_source(), ingested_at=INGESTED_AT)
    path = tmp_path / "broken.csv"
    path.write_text("source_id,name\nSYN-900,Synthetic\n", encoding="utf-8")
    source = CsvFileSource(path=path, _descriptor=SYNTHETIC_DESCRIPTOR)

    outcome = ingest_with_fallback(
        source, ingested_at=INGESTED_AT, previous=previous
    )

    assert outcome.applied is False
    assert outcome.retained_previous is True
    assert outcome.reason_code == "source_unreadable"
    assert outcome.result is previous


def test_dataset_with_no_valid_rows_retains_the_previous_dataset(tmp_path: Path):
    previous: IngestionResult = ingest(synthetic_csv_source(), ingested_at=INGESTED_AT)
    path = tmp_path / "all_invalid.csv"
    path.write_text(
        "source_id,name,latitude,longitude,address,opening_hours,access_notes,source_updated_at\n"
        "SYN-901,Synthetic Out Of Region,35.6895,139.6917,4 Synthetic Rd,24/7,Lobby,2026-08-15T00:00:00Z\n",
        encoding="utf-8",
    )
    source = CsvFileSource(path=path, _descriptor=SYNTHETIC_DESCRIPTOR)

    outcome = ingest_with_fallback(source, ingested_at=INGESTED_AT, previous=previous)

    assert outcome.applied is False
    assert outcome.reason_code == "empty_dataset"
    assert outcome.result.record_count == previous.record_count
