"""Row-level normalization and validation.

Rejections drop a row entirely; warnings keep the row but record that a field
is unknown. Missing access notes or unparseable hours are warnings, because
dropping a real AED is worse than showing it with an explicit unknown label.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from data.aed.hours import parse_opening_hours
from data.aed.models import AedRecord, GeoPoint, SourceRow
from data.aed.region import DEFAULT_REGION, RegionBounds

_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class NormalizationIssue:
    """One validation finding for a source row."""

    row_number: int
    source_id: str
    reason_code: str
    detail: str


@dataclass(frozen=True)
class NormalizedRow:
    """A normalized row plus any non-fatal findings."""

    record: AedRecord
    warnings: tuple[NormalizationIssue, ...]


def normalize_row(
    row: SourceRow,
    *,
    ingested_at: datetime,
    region: RegionBounds = DEFAULT_REGION,
) -> NormalizedRow | NormalizationIssue:
    """Normalize one source row, or return the rejection that stopped it."""

    values = row.values
    descriptor = row.descriptor
    source_id = values.get("source_id", "").strip()

    if not source_id:
        return NormalizationIssue(
            row_number=row.row_number,
            source_id="",
            reason_code="missing_source_id",
            detail="source_id is empty",
        )

    if not descriptor.source_url:
        return NormalizationIssue(
            row_number=row.row_number,
            source_id=source_id,
            reason_code="missing_source_metadata",
            detail="source descriptor has no source_url",
        )

    point = _parse_point(values.get("latitude", ""), values.get("longitude", ""))
    if point is None:
        return NormalizationIssue(
            row_number=row.row_number,
            source_id=source_id,
            reason_code="invalid_coordinates",
            detail=f"latitude={values.get('latitude', '')!r} longitude={values.get('longitude', '')!r}",
        )

    if not region.contains(point):
        return NormalizationIssue(
            row_number=row.row_number,
            source_id=source_id,
            reason_code="coordinates_out_of_region",
            detail=f"{point.latitude},{point.longitude} outside region {region.name}",
        )

    address = _collapse_whitespace(values.get("address", ""))
    if not address:
        return NormalizationIssue(
            row_number=row.row_number,
            source_id=source_id,
            reason_code="missing_address",
            detail="address is empty",
        )

    warnings: list[NormalizationIssue] = []
    quality_notes: list[str] = []

    name = _collapse_whitespace(values.get("name", "")) or f"AED {source_id}"
    if not _collapse_whitespace(values.get("name", "")):
        warnings.append(
            NormalizationIssue(
                row_number=row.row_number,
                source_id=source_id,
                reason_code="missing_name",
                detail="name is empty; a placeholder name was generated",
            )
        )
        quality_notes.append("missing_name")

    opening_hours = parse_opening_hours(values.get("opening_hours", ""))
    if not opening_hours.known:
        warnings.append(
            NormalizationIssue(
                row_number=row.row_number,
                source_id=source_id,
                reason_code="unknown_opening_hours",
                detail=opening_hours.parse_note or "opening hours could not be parsed",
            )
        )
        quality_notes.append("unknown_opening_hours")

    access_notes = _collapse_whitespace(values.get("access_notes", "")) or None
    access_notes_known = access_notes is not None
    if not access_notes_known:
        warnings.append(
            NormalizationIssue(
                row_number=row.row_number,
                source_id=source_id,
                reason_code="missing_access_notes",
                detail="no access notes supplied; access stays unknown",
            )
        )
        quality_notes.append("missing_access_notes")

    source_updated_at = _parse_timestamp(values.get("source_updated_at", ""))
    if source_updated_at is None:
        warnings.append(
            NormalizationIssue(
                row_number=row.row_number,
                source_id=source_id,
                reason_code="missing_source_update_time",
                detail=f"source_updated_at={values.get('source_updated_at', '')!r}",
            )
        )
        quality_notes.append("missing_source_update_time")

    record = AedRecord(
        stable_id=build_stable_id(descriptor.source_system, source_id),
        source_id=source_id,
        source_system=descriptor.source_system,
        name=name,
        point=point,
        address=address,
        opening_hours=opening_hours,
        access_notes=access_notes,
        access_notes_known=access_notes_known,
        source_url=descriptor.source_url,
        source_updated_at=source_updated_at,
        ingested_at=ingested_at,
        dataset_version=descriptor.dataset_version,
        data_quality_notes=tuple(quality_notes),
        source_location_id=_collapse_whitespace(values.get("location_id", "")) or None,
    )
    return NormalizedRow(record=record, warnings=tuple(warnings))


def build_stable_id(source_system: str, source_id: str) -> str:
    """Deterministic identifier that survives re-ingestion of the same row."""

    return f"{_slugify(source_system)}:{_slugify(source_id)}"


def _slugify(value: str) -> str:
    return _SLUG.sub("-", value.strip().lower()).strip("-")


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _parse_point(latitude: str, longitude: str) -> GeoPoint | None:
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        return None
    return GeoPoint(latitude=lat, longitude=lng)


def _parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
