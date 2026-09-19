"""AED ingestion and normalization pipeline.

This package converts local CSV/JSON exports into normalized, validated AED
records. No government dataset has been selected or approved for this
prototype, so the only inputs shipped in the repository are the clearly
labeled synthetic fixtures under ``data/fixtures/``.
"""

from data.aed.models import (
    AedRecord,
    AvailabilityStatus,
    GeoPoint,
    OpeningHours,
    OpeningWindow,
    SourceDescriptor,
    SourceRow,
)
from data.aed.pipeline import (
    IngestionOutcome,
    IngestionResult,
    RowRejection,
    RowWarning,
    ingest,
    ingest_with_fallback,
)
from data.aed.sources import (
    AedSourceAdapter,
    CsvFileSource,
    FieldMapping,
    JsonFileSource,
    SYNTHETIC_FIELD_MAPPING,
)

__all__ = [
    "AedRecord",
    "AedSourceAdapter",
    "AvailabilityStatus",
    "CsvFileSource",
    "FieldMapping",
    "GeoPoint",
    "IngestionOutcome",
    "IngestionResult",
    "JsonFileSource",
    "OpeningHours",
    "OpeningWindow",
    "RowRejection",
    "RowWarning",
    "SYNTHETIC_FIELD_MAPPING",
    "SourceDescriptor",
    "SourceRow",
    "ingest",
    "ingest_with_fallback",
]
