from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApiError(Exception):
    code: str
    status: int
    message: str
    details: dict | None = None


def unauthorized(message: str = "Access denied") -> ApiError:
    return ApiError("unauthorized", 403, message)


def stale(field: str, actual: int) -> ApiError:
    return ApiError("stale_revision", 409, "Revision is stale", {field: actual})


def unavailable() -> ApiError:
    return ApiError("unavailable", 503, "Service is unavailable")
