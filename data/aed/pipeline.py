"""Dataset-level ingestion: read a source, normalize rows, resolve duplicates.

``ingest_with_fallback`` implements the documented behavior that a failed
ingestion run retains the last valid dataset instead of publishing an empty
one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from data.aed.models import AedRecord, SourceDescriptor
from data.aed.normalize import NormalizationIssue, NormalizedRow, normalize_row
from data.aed.region import DEFAULT_REGION, RegionBounds
from data.aed.sources import AedSourceAdapter, SourceReadError

RowRejection = NormalizationIssue
RowWarning = NormalizationIssue


@dataclass(frozen=True)
class IngestionResult:
    """A normalized dataset plus everything that was dropped or flagged."""

    descriptor: SourceDescriptor
    ingested_at: datetime
    records: tuple[AedRecord, ...]
    rejections: tuple[RowRejection, ...]
    warnings: tuple[RowWarning, ...]
    rows_read: int

    @property
    def dataset_version(self) -> str:
        return self.descriptor.dataset_version

    @property
    def record_count(self) -> int:
        return len(self.records)

    def by_stable_id(self) -> dict[str, AedRecord]:
        return {record.stable_id: record for record in self.records}


@dataclass(frozen=True)
class IngestionOutcome:
    """What the caller should publish, and whether the new dataset applied."""

    result: IngestionResult
    applied: bool
    reason_code: str
    detail: str = ""

    @property
    def retained_previous(self) -> bool:
        return not self.applied


def ingest(
    source: AedSourceAdapter,
    *,
    ingested_at: datetime,
    region: RegionBounds = DEFAULT_REGION,
) -> IngestionResult:
    """Normalize every row of ``source`` and deduplicate by stable ID."""

    accepted: dict[str, AedRecord] = {}
    rejections: list[RowRejection] = []
    warnings: list[RowWarning] = []
    rows_read = 0

    for row in source.rows():
        rows_read += 1
        outcome = normalize_row(row, ingested_at=ingested_at, region=region)
        if isinstance(outcome, NormalizationIssue):
            rejections.append(outcome)
            continue

        assert isinstance(outcome, NormalizedRow)
        record = outcome.record
        warnings.extend(outcome.warnings)

        existing = accepted.get(record.stable_id)
        if existing is None:
            accepted[record.stable_id] = record
            continue

        kept, dropped = _resolve_duplicate(existing, record)
        accepted[record.stable_id] = kept
        rejections.append(
            RowRejection(
                row_number=row.row_number,
                source_id=record.source_id,
                reason_code="duplicate_source_id",
                detail=(
                    f"stable_id {record.stable_id} already ingested; kept the record "
                    f"updated at {_stamp(kept.source_updated_at)}, dropped "
                    f"{_stamp(dropped.source_updated_at)}"
                ),
            )
        )

    records = tuple(sorted(accepted.values(), key=lambda record: record.stable_id))
    return IngestionResult(
        descriptor=source.descriptor,
        ingested_at=ingested_at,
        records=records,
        rejections=tuple(rejections),
        warnings=tuple(warnings),
        rows_read=rows_read,
    )


def ingest_with_fallback(
    source: AedSourceAdapter,
    *,
    ingested_at: datetime,
    previous: IngestionResult | None = None,
    region: RegionBounds = DEFAULT_REGION,
) -> IngestionOutcome:
    """Ingest, but keep ``previous`` when the new dataset is unusable."""

    try:
        result = ingest(source, ingested_at=ingested_at, region=region)
    except SourceReadError as exc:
        if previous is None:
            raise
        return IngestionOutcome(
            result=previous,
            applied=False,
            reason_code="source_unreadable",
            detail=str(exc),
        )

    if not result.records:
        if previous is None:
            return IngestionOutcome(
                result=result,
                applied=True,
                reason_code="empty_dataset_no_previous",
                detail="no valid records and no previous dataset to retain",
            )
        return IngestionOutcome(
            result=previous,
            applied=False,
            reason_code="empty_dataset",
            detail=f"{len(result.rejections)} rows rejected, 0 valid records",
        )

    return IngestionOutcome(result=result, applied=True, reason_code="applied")


def _resolve_duplicate(first: AedRecord, second: AedRecord) -> tuple[AedRecord, AedRecord]:
    """Keep the more recently updated record; ties keep the first one seen."""

    first_stamp = first.source_updated_at
    second_stamp = second.source_updated_at
    if second_stamp is not None and (first_stamp is None or second_stamp > first_stamp):
        return second, first
    return first, second


def _stamp(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "unknown"
