"""Adapter for the Taiwan MOHW national AED open-data CSV."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from data.aed.models import SourceDescriptor, SourceRow
from data.aed.sources import SourceReadError

MOHW_SOURCE_URL = "https://tw-aed.mohw.gov.tw/openData?t=csv"
MOHW_DATASET_PAGE_URL = "https://data.gov.tw/dataset/12063"
MOHW_LICENSE_URL = "https://data.gov.tw/license"
MOHW_LICENSE_NOTE = (
    "Government Data Open License, version 1.0 "
    f"({MOHW_LICENSE_URL}); source agency: Ministry of Health and Welfare."
)

MOHW_COLUMNS = (
    "場所ID",
    "場所名稱",
    "場所縣市",
    "場所區域",
    "場所地址",
    "場所分類",
    "場所類型",
    "場所描述",
    "AEDID",
    "AED放置地點",
    "AED地點描述",
    "地點LAT",
    "地點LNG",
    "周一至周五起",
    "周一至周五迄",
    "周六起",
    "周六迄",
    "周日起",
    "周日迄",
    "開放使用時間備註",
    "開放時間緊急連絡電話",
)

_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


@dataclass(frozen=True)
class MohwCsvSource:
    """Read one locally cached MOHW CSV export."""

    path: Path
    _descriptor: SourceDescriptor
    source_updated_at: datetime

    @property
    def descriptor(self) -> SourceDescriptor:
        return self._descriptor

    def rows(self) -> Iterator[SourceRow]:
        try:
            handle = self.path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceReadError(f"cannot open {self.path}: {exc}") from exc

        try:
            with handle:
                reader = csv.DictReader(handle, strict=True)
                if reader.fieldnames is None:
                    raise SourceReadError(f"{self.path} has no header row")
                available = {name.strip() for name in reader.fieldnames}
                missing = tuple(name for name in MOHW_COLUMNS if name not in available)
                if missing:
                    raise SourceReadError(
                        f"{self.path} is missing MOHW columns: {', '.join(missing)}"
                    )
                for row_number, raw in enumerate(reader, start=2):
                    yield SourceRow(
                        row_number=row_number,
                        values=map_mohw_row(raw, self.source_updated_at),
                        descriptor=self._descriptor,
                    )
        except (UnicodeDecodeError, csv.Error) as exc:
            raise SourceReadError(f"cannot parse {self.path}: {exc}") from exc


def map_mohw_row(raw: Mapping[str, str | None], source_updated_at: datetime) -> dict[str, str]:
    """Map the published Chinese columns into the ingestion contract."""

    return {
        "source_id": _value(raw, "AEDID"),
        "location_id": _value(raw, "場所ID"),
        "name": _value(raw, "場所名稱"),
        "latitude": _value(raw, "地點LAT"),
        "longitude": _value(raw, "地點LNG"),
        "address": _value(raw, "場所地址"),
        "opening_hours": build_mohw_opening_hours(raw),
        "access_notes": build_mohw_access_notes(raw),
        "source_updated_at": source_updated_at.isoformat(),
    }


def build_mohw_opening_hours(raw: Mapping[str, str | None]) -> str:
    """Convert weekday/weekend columns without treating blanks as closed."""

    groups = (
        ("Mon-Fri", "周一至周五起", "周一至周五迄"),
        ("Sat", "周六起", "周六迄"),
        ("Sun", "周日起", "周日迄"),
    )
    segments: list[str] = []
    for days, start_column, end_column in groups:
        start_raw = _value(raw, start_column)
        end_raw = _value(raw, end_column)
        if not start_raw or not end_raw:
            segments.append(f"{days} unknown")
            continue
        start = _normalize_clock(start_raw)
        end = _normalize_clock(end_raw)
        if start is None or end is None:
            segments.append(f"{days} invalid[{start_raw}-{end_raw}]")
            continue
        segments.append(f"{days} {start}-{end}")
    return "; ".join(segments)


def build_mohw_access_notes(raw: Mapping[str, str | None]) -> str:
    """Preserve placement, access caveats, and the published contact number."""

    fields = (
        ("AED放置地點", "AED放置地點"),
        ("AED地點描述", "AED地點描述"),
        ("開放使用時間備註", "開放使用時間備註"),
        ("開放時間緊急連絡電話", "開放時間緊急連絡電話"),
    )
    notes = [f"{label}：{value}" for label, column in fields if (value := _value(raw, column))]
    return "；".join(notes)


def _normalize_clock(value: str) -> str | None:
    match = _CLOCK.fullmatch(value.strip())
    if match is None:
        return None
    hour, minute, second = (int(part or 0) for part in match.groups())
    if hour > 24 or minute > 59 or second != 0:
        return None
    if hour == 24 and minute != 0:
        return None
    return f"{hour:02d}:{minute:02d}"


def _value(raw: Mapping[str, str | None], column: str) -> str:
    return (raw.get(column) or "").strip()
