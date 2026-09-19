"""Opening-hours parsing for a restricted, explicitly supported syntax.

Supported forms (case-insensitive, ``;`` or newline separated):

* ``24/7``, ``24 hours``, ``always``  -> always open
* ``Mon-Fri 08:00-18:00``            -> weekday range with one time window
* ``Sat 09:00-13:00, 14:00-17:00``   -> several windows for the same days
* ``Mon 22:00-02:00``                -> window running past midnight
* ``Sat unknown``                    -> no published Saturday hours
* empty, ``unknown``, ``n/a``, ``未知`` -> unknown

Anything else stays ``unknown`` with the raw text and a parse note preserved.
The parser never guesses: an unparsed value must not become "closed".

Two endpoint rules keep that promise:

* ``24`` names the end of the day, so ``24:00`` is the only valid hour-24
  endpoint. ``24:30`` is rejected rather than read as 00:30 the next day.
* Equal endpoints such as ``08:00-08:00`` are rejected. A full day must be
  written with the explicit always-open tokens or as ``00:00-24:00``; it is
  never inferred from a degenerate range.
"""

from __future__ import annotations

import re

from data.aed.models import MINUTES_PER_DAY, WEEKDAY_NAMES, OpeningHours, OpeningWindow

_ALWAYS_OPEN_TOKENS = frozenset(
    {"24/7", "24-7", "247", "24 hours", "24hr", "24hrs", "24小時", "全天", "always", "always open"}
)
_UNKNOWN_TOKENS = frozenset({"", "unknown", "unspecified", "n/a", "na", "-", "未知", "不詳", "不明"})

_TIME_RANGE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")
_DAY_TOKEN = re.compile(r"^[a-z]{3}(?:\s*-\s*[a-z]{3})?$")


def parse_opening_hours(raw: str | None) -> OpeningHours:
    """Parse ``raw`` into structured hours, preserving the original text."""

    text = (raw or "").strip()
    normalized = text.lower()
    if normalized in _UNKNOWN_TOKENS:
        return OpeningHours.unknown(raw=text or None, parse_note="no_opening_hours_supplied")
    if normalized in _ALWAYS_OPEN_TOKENS:
        return OpeningHours(known=True, always_open=True, windows=(), raw=text)

    windows: list[OpeningWindow] = []
    unknown_weekdays: set[int] = set()
    for segment in _split_segments(normalized):
        unknown_days = _parse_unknown_segment(segment)
        if unknown_days is not None:
            unknown_weekdays.update(unknown_days)
            continue
        parsed = _parse_segment(segment)
        if parsed is None:
            return OpeningHours.unknown(raw=text, parse_note=f"unparsed_segment:{segment}")
        windows.extend(parsed)

    if not windows:
        note = "all_weekdays_unknown" if unknown_weekdays else "no_windows_parsed"
        return OpeningHours.unknown(raw=text, parse_note=note)

    ordered = tuple(sorted(set(windows), key=lambda w: (w.weekday, w.start_minute, w.end_minute)))
    return OpeningHours(
        known=True,
        always_open=False,
        windows=ordered,
        unknown_weekdays=tuple(sorted(unknown_weekdays)),
        raw=text,
    )


def _split_segments(normalized: str) -> list[str]:
    parts = re.split(r"[;\n]", normalized)
    return [part.strip() for part in parts if part.strip()]


def _parse_segment(segment: str) -> list[OpeningWindow] | None:
    """Parse ``mon-fri 08:00-18:00, 19:00-21:00`` into windows."""

    fields = [field.strip() for field in segment.split(",") if field.strip()]
    if not fields:
        return None

    day_part, _, first_time = fields[0].partition(" ")
    day_part = day_part.strip()
    first_time = first_time.strip()
    if not _DAY_TOKEN.match(day_part) or not first_time:
        return None

    weekdays = _parse_weekdays(day_part)
    if weekdays is None:
        return None

    time_ranges = [first_time, *fields[1:]]
    windows: list[OpeningWindow] = []
    for time_range in time_ranges:
        bounds = _parse_time_range(time_range)
        if bounds is None:
            return None
        start, end = bounds
        for weekday in weekdays:
            windows.append(OpeningWindow(weekday=weekday, start_minute=start, end_minute=end))
    return windows


def _parse_unknown_segment(segment: str) -> list[int] | None:
    day_part, separator, status = segment.partition(" ")
    if not separator or status.strip() != "unknown" or not _DAY_TOKEN.match(day_part):
        return None
    return _parse_weekdays(day_part)


def _parse_weekdays(day_part: str) -> list[int] | None:
    if "-" in day_part:
        start_name, _, end_name = day_part.partition("-")
        start_name = start_name.strip()
        end_name = end_name.strip()
        if start_name not in WEEKDAY_NAMES or end_name not in WEEKDAY_NAMES:
            return None
        start = WEEKDAY_NAMES.index(start_name)
        end = WEEKDAY_NAMES.index(end_name)
        span = (end - start) % 7
        return [(start + offset) % 7 for offset in range(span + 1)]
    if day_part not in WEEKDAY_NAMES:
        return None
    return [WEEKDAY_NAMES.index(day_part)]


def _parse_time_range(time_range: str) -> tuple[int, int] | None:
    match = _TIME_RANGE.match(time_range.strip())
    if match is None:
        return None
    start_hour, start_minute, end_hour, end_minute = (int(value) for value in match.groups())
    if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
        return None
    if not (0 <= end_hour <= 24 and 0 <= end_minute <= 59):
        return None
    # 24 names the end of the day, so 24:00 is the only valid hour-24 value.
    if end_hour == 24 and end_minute != 0:
        return None

    start = start_hour * 60 + start_minute
    end = end_hour * 60 + end_minute
    if end == start:
        # Equal endpoints are ambiguous: they could mean a zero-length window
        # or a full day. Never infer always-open from a time range; the
        # explicit tokens ("24/7") are the supported way to say that.
        return None
    if end < start:
        # Window runs past midnight into the next day.
        end += MINUTES_PER_DAY
    return start, end
