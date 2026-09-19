"""Validate and atomically import one MOHW AED CSV into PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.services.postgres_data.aed import PostgresAedCatalogRepository
from data.aed.mohw import MOHW_LICENSE_NOTE, MOHW_SOURCE_URL, MohwCsvSource
from data.aed.models import SourceDescriptor
from data.aed.pipeline import ingest

MAX_REJECTION_RATIO = 0.5


def import_aed_csv(
    path: Path,
    database_url: str,
    *,
    dataset_version: str | None = None,
) -> dict[str, object]:
    path = path.resolve()
    now = datetime.now(timezone.utc)
    source_updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    descriptor = SourceDescriptor(
        source_system="mohw-taiwan-aed",
        source_url=MOHW_SOURCE_URL,
        dataset_version=dataset_version or path.stem,
        retrieved_at=now,
        synthetic=False,
        license_note=MOHW_LICENSE_NOTE,
    )
    result = ingest(
        MohwCsvSource(
            path=path,
            _descriptor=descriptor,
            source_updated_at=source_updated_at,
        ),
        ingested_at=now,
    )
    rejection_ratio = len(result.rejections) / result.rows_read if result.rows_read else 1.0
    if result.record_count == 0 or rejection_ratio > MAX_REJECTION_RATIO:
        raise RuntimeError(
            "AED CSV validation failed: "
            f"rows={result.rows_read}, records={result.record_count}, "
            f"rejections={len(result.rejections)}"
        )
    imported = PostgresAedCatalogRepository(database_url).replace_dataset(
        descriptor,
        result.records,
        imported_at=now,
    )
    return {
        "datasetVersion": descriptor.dataset_version,
        "rowsRead": result.rows_read,
        "recordsImported": imported,
        "rejections": len(result.rejections),
        "warnings": len(result.warnings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--dataset-version", default=os.getenv("AED_DATASET_VERSION"))
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    print(json.dumps(import_aed_csv(
        arguments.csv,
        arguments.database_url,
        dataset_version=arguments.dataset_version,
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
