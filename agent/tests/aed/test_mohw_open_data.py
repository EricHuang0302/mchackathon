"""MOHW national AED adapter and resilient local-cache updates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

from data.aed.hours import parse_opening_hours
from data.aed.mohw import MOHW_LICENSE_NOTE, MOHW_SOURCE_URL, MohwCsvSource
from data.aed.models import AvailabilityStatus, SourceDescriptor
from data.aed.pipeline import ingest
from data.aed.sources import SourceReadError
from data.aed.update_mohw import (
    MohwUpdateError,
    load_cached_mohw_source,
    update_mohw_cache,
)
from app.services.aed.availability import evaluate_availability

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "fixtures"
    / "synthetic_mohw_aed_sample.csv"
)
NOW = datetime(2026, 9, 19, 10, 30, tzinfo=timezone.utc)
UPDATED = datetime(2026, 9, 19, 10, 15, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, body: bytes, *, filename: str = "AED20260919.csv") -> None:
        self._body = body
        self._offset = 0
        self.headers = Message()
        self.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        self.headers["Last-Modified"] = "Sat, 19 Sep 2026 10:15:00 GMT"

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        source_system="mohw-taiwan-aed",
        source_url=MOHW_SOURCE_URL,
        dataset_version="AED20260919",
        retrieved_at=NOW,
        synthetic=False,
        license_note=MOHW_LICENSE_NOTE,
    )


def _opener(body: bytes):
    def open_response(request: Request, *, timeout: float) -> FakeResponse:
        assert request.full_url == MOHW_SOURCE_URL
        assert timeout > 0
        return FakeResponse(body)

    return open_response


def test_mohw_adapter_maps_ids_coordinates_hours_and_access_notes():
    source = MohwCsvSource(
        path=FIXTURE,
        _descriptor=_descriptor(),
        source_updated_at=UPDATED,
    )

    rows = list(source.rows())
    first = rows[0].values

    assert first["source_id"] == "synthetic-aed-1"
    assert first["location_id"] == "synthetic-location-1"
    assert first["latitude"] == "25.0478"
    assert first["longitude"] == "121.5170"
    assert first["address"] == "臺北市中正區測試路1號"
    assert first["opening_hours"] == (
        "Mon-Fri 08:00-18:00; Sat 09:00-12:00; Sun unknown"
    )
    assert "AED放置地點：一樓服務台旁" in first["access_notes"]
    assert "開放使用時間備註：週日資訊未提供" in first["access_notes"]
    assert first["source_updated_at"] == UPDATED.isoformat()

    result = ingest(source, ingested_at=NOW)
    record = result.by_stable_id()["mohw-taiwan-aed:synthetic-aed-1"]
    assert record.source_location_id == "synthetic-location-1"
    assert record.opening_hours.known
    assert record.opening_hours.unknown_weekdays == (6,)
    assert record.source_updated_at == UPDATED
    assert not result.descriptor.synthetic
    assert "Government Data Open License" in result.descriptor.license_note


def test_partial_week_schedule_stays_unknown_for_unpublished_day():
    hours = parse_opening_hours(
        "Mon-Fri 08:00-18:00; Sat 09:00-12:00; Sun unknown"
    )

    assert hours.known
    assert hours.unknown_weekdays == (6,)
    assert len(hours.windows) == 6


def test_partial_week_schedule_does_not_guess_missing_sunday_is_closed():
    source = MohwCsvSource(
        path=FIXTURE,
        _descriptor=_descriptor(),
        source_updated_at=UPDATED,
    )
    record = ingest(source, ingested_at=NOW).by_stable_id()[
        "mohw-taiwan-aed:synthetic-aed-1"
    ]

    sunday = datetime(2026, 9, 20, 2, 0, tzinfo=timezone.utc)
    assessment = evaluate_availability(record, at=sunday)

    assert assessment.status is AvailabilityStatus.UNKNOWN
    assert assessment.reason_code == "opening_hours_unknown_for_weekday"
    assert "opening_hours_partial" in assessment.uncertainty


def test_update_publishes_validated_csv_and_metadata_atomically(tmp_path):
    body = FIXTURE.read_bytes()

    update = update_mohw_cache(
        tmp_path,
        now=NOW,
        opener=_opener(body),
    )
    source = load_cached_mohw_source(tmp_path)
    result = ingest(source, ingested_at=NOW)
    metadata = json.loads(update.metadata_path.read_text(encoding="utf-8"))

    assert update.dataset_version == "AED20260919"
    assert update.rows_read == 2
    assert update.record_count == 2
    assert result.record_count == 2
    assert metadata["source_url"] == MOHW_SOURCE_URL
    assert metadata["dataset_page_url"] == "https://data.gov.tw/dataset/12063"
    assert metadata["license_url"] == "https://data.gov.tw/license"
    assert metadata["source_updated_at"] == UPDATED.isoformat()
    assert metadata["sha256"] == update.sha256


def test_failed_update_keeps_previous_active_generation(tmp_path):
    body = FIXTURE.read_bytes()
    first = update_mohw_cache(tmp_path, now=NOW, opener=_opener(body))
    current_before = (tmp_path / "current.json").read_bytes()
    invalid = b'"wrong","header"\n"value","value"\n'

    with pytest.raises(MohwUpdateError, match="active cache retained"):
        update_mohw_cache(tmp_path, now=NOW, opener=_opener(invalid))

    assert (tmp_path / "current.json").read_bytes() == current_before
    source = load_cached_mohw_source(tmp_path)
    assert source.path == first.data_path
    assert ingest(source, ingested_at=NOW).record_count == 2


def test_network_failure_keeps_previous_active_generation(tmp_path):
    update_mohw_cache(
        tmp_path,
        now=NOW,
        opener=_opener(FIXTURE.read_bytes()),
    )
    current_before = (tmp_path / "current.json").read_bytes()

    def unavailable(request: Request, *, timeout: float) -> FakeResponse:
        raise URLError("synthetic network failure")

    with pytest.raises(MohwUpdateError, match="active cache retained"):
        update_mohw_cache(tmp_path, now=NOW, opener=unavailable)

    assert (tmp_path / "current.json").read_bytes() == current_before
    assert ingest(load_cached_mohw_source(tmp_path), ingested_at=NOW).record_count == 2


def test_cache_loader_rejects_checksum_mismatch(tmp_path):
    update = update_mohw_cache(
        tmp_path,
        now=NOW,
        opener=_opener(FIXTURE.read_bytes()),
    )
    update.data_path.write_bytes(b"changed")

    with pytest.raises(SourceReadError, match="checksum"):
        load_cached_mohw_source(tmp_path)
