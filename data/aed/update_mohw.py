"""Download, validate, and atomically publish the MOHW AED CSV cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from data.aed.mohw import (
    MOHW_DATASET_PAGE_URL,
    MOHW_LICENSE_NOTE,
    MOHW_LICENSE_URL,
    MOHW_SOURCE_URL,
    MohwCsvSource,
)
from data.aed.models import SourceDescriptor
from data.aed.pipeline import ingest
from data.aed.sources import SourceReadError

CACHE_SCHEMA_VERSION = 1
DEFAULT_CACHE_DIR = Path("var/aed")
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_REJECTION_RATIO = 0.5


class DownloadResponse(Protocol):
    headers: Message

    def read(self, size: int = -1) -> bytes: ...

    def __enter__(self) -> "DownloadResponse": ...

    def __exit__(self, *args: object) -> None: ...


class OpenUrl(Protocol):
    def __call__(self, request: Request, *, timeout: float) -> DownloadResponse: ...


class MohwUpdateError(RuntimeError):
    """A remote update failed before the active cache pointer changed."""


@dataclass(frozen=True)
class MohwUpdateResult:
    dataset_version: str
    rows_read: int
    record_count: int
    sha256: str
    data_path: Path
    metadata_path: Path


def update_mohw_cache(
    cache_dir: Path,
    *,
    source_url: str = MOHW_SOURCE_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    now: datetime | None = None,
    opener: OpenUrl = urlopen,
) -> MohwUpdateResult:
    """Fetch and validate a new generation, then switch ``current.json``."""

    retrieved_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cache_dir = cache_dir.resolve()
    versions_dir = cache_dir / "versions"
    versions_dir.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        temporary_path, headers, digest, byte_count = _download(
            versions_dir,
            source_url=source_url,
            timeout_seconds=timeout_seconds,
            opener=opener,
        )
        source_updated_at = _source_updated_at(headers, retrieved_at)
        dataset_version = _dataset_version(headers, source_updated_at, digest)
        descriptor = SourceDescriptor(
            source_system="mohw-taiwan-aed",
            source_url=source_url,
            dataset_version=dataset_version,
            retrieved_at=retrieved_at,
            synthetic=False,
            license_note=MOHW_LICENSE_NOTE,
        )
        source = MohwCsvSource(
            path=temporary_path,
            _descriptor=descriptor,
            source_updated_at=source_updated_at,
        )
        result = ingest(source, ingested_at=retrieved_at)
        rejection_ratio = (
            len(result.rejections) / result.rows_read if result.rows_read else 1.0
        )
        if (
            result.rows_read == 0
            or result.record_count == 0
            or rejection_ratio > MAX_REJECTION_RATIO
        ):
            raise MohwUpdateError(
                "downloaded dataset failed AED row validation; active cache retained"
            )

        stem = f"{_safe_name(dataset_version)}-{digest[:12]}"
        data_path = versions_dir / f"{stem}.csv"
        metadata_path = versions_dir / f"{stem}.json"
        os.replace(temporary_path, data_path)
        temporary_path = None

        metadata = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "source_system": descriptor.source_system,
            "source_url": source_url,
            "dataset_page_url": MOHW_DATASET_PAGE_URL,
            "license": MOHW_LICENSE_NOTE,
            "license_url": MOHW_LICENSE_URL,
            "dataset_version": dataset_version,
            "retrieved_at": retrieved_at.isoformat(),
            "source_updated_at": source_updated_at.isoformat(),
            "sha256": digest,
            "byte_count": byte_count,
            "rows_read": result.rows_read,
            "record_count": result.record_count,
            "rejection_count": len(result.rejections),
            "warning_count": len(result.warnings),
            "data_file": data_path.name,
        }
        _atomic_json(metadata_path, metadata)
        _atomic_json(
            cache_dir / "current.json",
            {
                "schema_version": CACHE_SCHEMA_VERSION,
                "data": str(data_path.relative_to(cache_dir)).replace("\\", "/"),
                "metadata": str(metadata_path.relative_to(cache_dir)).replace("\\", "/"),
            },
        )
        return MohwUpdateResult(
            dataset_version=dataset_version,
            rows_read=result.rows_read,
            record_count=result.record_count,
            sha256=digest,
            data_path=data_path,
            metadata_path=metadata_path,
        )
    except MohwUpdateError:
        raise
    except (HTTPError, URLError, OSError, SourceReadError, ValueError) as exc:
        raise MohwUpdateError(f"MOHW AED update failed; active cache retained: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_cached_mohw_source(cache_dir: Path) -> MohwCsvSource:
    """Load and verify the generation named by the atomic cache pointer."""

    cache_dir = cache_dir.resolve()
    try:
        current = json.loads((cache_dir / "current.json").read_text(encoding="utf-8"))
        if current["schema_version"] != CACHE_SCHEMA_VERSION:
            raise ValueError("unsupported cache pointer schema")
        data_path = _cache_member(cache_dir, current["data"])
        metadata_path = _cache_member(cache_dir, current["metadata"])
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata["schema_version"] != CACHE_SCHEMA_VERSION:
            raise ValueError("unsupported metadata schema")
        digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
        if digest != metadata["sha256"]:
            raise ValueError("cached CSV checksum does not match metadata")
        if metadata["data_file"] != data_path.name:
            raise ValueError("cached CSV filename does not match metadata")
        descriptor = SourceDescriptor(
            source_system=metadata["source_system"],
            source_url=metadata["source_url"],
            dataset_version=metadata["dataset_version"],
            retrieved_at=datetime.fromisoformat(metadata["retrieved_at"]),
            synthetic=False,
            license_note=metadata["license"],
        )
        return MohwCsvSource(
            path=data_path,
            _descriptor=descriptor,
            source_updated_at=datetime.fromisoformat(metadata["source_updated_at"]),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SourceReadError(f"cannot load MOHW AED cache at {cache_dir}: {exc}") from exc


def _download(
    directory: Path,
    *,
    source_url: str,
    timeout_seconds: float,
    opener: OpenUrl,
) -> tuple[Path, Message, str, int]:
    request = Request(
        source_url,
        headers={"Accept": "text/csv", "User-Agent": "first-aid-copilot-aed-updater/1"},
    )
    handle, temporary_name = tempfile.mkstemp(prefix=".mohw-", suffix=".csv", dir=directory)
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with os.fdopen(handle, "wb") as target, opener(
            request, timeout=timeout_seconds
        ) as response:
            while chunk := response.read(1024 * 1024):
                target.write(chunk)
                digest.update(chunk)
                byte_count += len(chunk)
            target.flush()
            os.fsync(target.fileno())
            headers = response.headers
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    if byte_count == 0:
        temporary_path.unlink(missing_ok=True)
        raise MohwUpdateError("download returned an empty body; active cache retained")
    return temporary_path, headers, digest.hexdigest(), byte_count


def _source_updated_at(headers: Message, fallback: datetime) -> datetime:
    value = headers.get("Last-Modified")
    if not value:
        return fallback
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dataset_version(headers: Message, updated_at: datetime, digest: str) -> str:
    disposition = headers.get("Content-Disposition", "")
    match = re.search(r"filename\s*=\s*[\"']?([^\"';]+)", disposition, re.IGNORECASE)
    if match:
        filename = Path(match.group(1).strip()).stem
        if filename:
            return filename
    return f"mohw-{updated_at:%Y%m%d}-{digest[:12]}"


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return safe or "mohw-aed"


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as target:
            json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _cache_member(cache_dir: Path, relative: str) -> Path:
    candidate = (cache_dir / relative).resolve()
    if cache_dir not in candidate.parents:
        raise ValueError("cache pointer escapes its cache directory")
    return candidate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.environ.get("AED_MOHW_CACHE_DIR", DEFAULT_CACHE_DIR)),
    )
    parser.add_argument(
        "--source-url",
        default=os.environ.get("AED_MOHW_SOURCE_URL", MOHW_SOURCE_URL),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("AED_MOHW_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
    )
    args = parser.parse_args(argv)
    try:
        result = update_mohw_cache(
            args.cache_dir,
            source_url=args.source_url,
            timeout_seconds=args.timeout,
        )
    except MohwUpdateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "datasetVersion": result.dataset_version,
                "rowsRead": result.rows_read,
                "recordCount": result.record_count,
                "sha256": result.sha256,
                "dataPath": str(result.data_path),
                "metadataPath": str(result.metadata_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
