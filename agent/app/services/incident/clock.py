"""Injected clocks.

Server receipt time must be observable and reproducible in tests, and it must
never be read from the wall clock inside a projection. Every service takes a
:class:`Clock`; the deterministic implementations below are what the test suite
and the ``eval/`` scenarios use.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


def utc(text: str) -> datetime:
    """Parse an ISO-8601 instant into an aware UTC ``datetime``.

    A naive value is rejected rather than assumed to be UTC, because clock
    uncertainty in offline clients is significant and must stay explicit.
    """
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone offset: {text!r}")
    return value.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    """Render an aware ``datetime`` as a stable UTC ISO-8601 string."""
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current instant as an aware UTC ``datetime``."""


class FixedClock:
    """A clock frozen at one instant."""

    __slots__ = ("_now",)

    def __init__(self, now: datetime | str) -> None:
        self._now = utc(now) if isinstance(now, str) else now.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._now


class ManualClock:
    """A clock advanced explicitly by the caller.

    Receipt ordering in the in-memory store does not depend on this clock, so a
    test may hold it still across a whole batch without creating ambiguity.
    """

    __slots__ = ("_now",)

    def __init__(self, start: datetime | str) -> None:
        self._now = utc(start) if isinstance(start, str) else start.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now = self._now + timedelta(seconds=seconds)
        return self._now

    def set(self, value: datetime | str) -> datetime:
        self._now = utc(value) if isinstance(value, str) else value.astimezone(timezone.utc)
        return self._now
