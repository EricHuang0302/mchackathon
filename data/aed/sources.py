"""Explicit source adapters for local AED exports.

Every input goes through an adapter that declares its provenance and its
column mapping. Network retrieval is kept in the source-specific update
module so parsing local files remains deterministic and testable.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from data.aed.models import SourceDescriptor, SourceRow

CANONICAL_FIELDS = (
    "source_id",
    "name",
    "latitude",
    "longitude",
    "address",
    "opening_hours",
    "access_notes",
    "source_updated_at",
)


@dataclass(frozen=True)
class FieldMapping:
    """Maps canonical field names to the column names of one source."""

    columns: dict[str, str]

    def extract(self, raw: dict[str, Any]) -> dict[str, str]:
        values: dict[str, str] = {}
        for canonical, column in self.columns.items():
            value = raw.get(column)
            values[canonical] = "" if value is None else str(value).strip()
        return values

    def missing_columns(self, available: list[str]) -> tuple[str, ...]:
        present = {name.strip() for name in available}
        return tuple(
            column for canonical, column in self.columns.items() if column not in present
        )


SYNTHETIC_FIELD_MAPPING = FieldMapping(
    columns={canonical: canonical for canonical in CANONICAL_FIELDS}
)


class AedSourceAdapter(Protocol):
    """Reads one local export and yields raw rows with provenance."""

    @property
    def descriptor(self) -> SourceDescriptor: ...

    def rows(self) -> Iterator[SourceRow]: ...


class SourceReadError(RuntimeError):
    """The source could not be read or is structurally invalid."""


@dataclass(frozen=True)
class CsvFileSource:
    """Reads a local CSV export through an explicit field mapping."""

    path: Path
    _descriptor: SourceDescriptor
    mapping: FieldMapping = SYNTHETIC_FIELD_MAPPING
    encoding: str = "utf-8"

    @property
    def descriptor(self) -> SourceDescriptor:
        return self._descriptor

    def rows(self) -> Iterator[SourceRow]:
        try:
            handle = self.path.open("r", encoding=self.encoding, newline="")
        except OSError as exc:  # pragma: no cover - surfaced through ingest_with_fallback
            raise SourceReadError(f"cannot open {self.path}: {exc}") from exc
        with handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise SourceReadError(f"{self.path} has no header row")
            missing = self.mapping.missing_columns(list(reader.fieldnames))
            if missing:
                raise SourceReadError(
                    f"{self.path} is missing mapped columns: {', '.join(missing)}"
                )
            for row_number, raw in enumerate(reader, start=2):
                yield SourceRow(
                    row_number=row_number,
                    values=self.mapping.extract(raw),
                    descriptor=self._descriptor,
                )


@dataclass(frozen=True)
class JsonFileSource:
    """Reads a local JSON export (a list, or an object with a records key)."""

    path: Path
    _descriptor: SourceDescriptor
    mapping: FieldMapping = SYNTHETIC_FIELD_MAPPING
    records_key: str = "records"
    encoding: str = "utf-8"

    @property
    def descriptor(self) -> SourceDescriptor:
        return self._descriptor

    def rows(self) -> Iterator[SourceRow]:
        try:
            payload = json.loads(self.path.read_text(encoding=self.encoding))
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceReadError(f"cannot parse {self.path}: {exc}") from exc

        if isinstance(payload, dict):
            payload = payload.get(self.records_key)
        if not isinstance(payload, list):
            raise SourceReadError(
                f"{self.path} does not contain a list of records under '{self.records_key}'"
            )

        for row_number, raw in enumerate(payload, start=1):
            if not isinstance(raw, dict):
                raise SourceReadError(f"{self.path} row {row_number} is not an object")
            yield SourceRow(
                row_number=row_number,
                values=self.mapping.extract(raw),
                descriptor=self._descriptor,
            )


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

SYNTHETIC_DESCRIPTOR = SourceDescriptor(
    source_system="synthetic-demo",
    source_url="https://example.invalid/synthetic-aed-dataset",
    dataset_version="synthetic-2026-09-01",
    retrieved_at=datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
    synthetic=True,
)


def synthetic_csv_source() -> CsvFileSource:
    """The labeled synthetic CSV fixture used for development and tests."""

    return CsvFileSource(
        path=FIXTURES_DIR / "synthetic_aed_sample.csv",
        _descriptor=SYNTHETIC_DESCRIPTOR,
    )


def synthetic_json_source() -> JsonFileSource:
    """The labeled synthetic JSON fixture, same records as the CSV fixture."""

    return JsonFileSource(
        path=FIXTURES_DIR / "synthetic_aed_sample.json",
        _descriptor=SYNTHETIC_DESCRIPTOR,
    )


def synthetic_malformed_csv_source() -> CsvFileSource:
    """A synthetic fixture whose rows deliberately fail validation."""

    return CsvFileSource(
        path=FIXTURES_DIR / "synthetic_aed_malformed.csv",
        _descriptor=SYNTHETIC_DESCRIPTOR,
    )
