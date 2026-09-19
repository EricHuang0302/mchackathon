"""Deterministic synthetic scenarios for the incident data layer.

Each module exposes ``NAME``, ``DESCRIPTION`` and ``run()``. ``run()`` returns
a JSON-shaped summary that is identical on every machine and every run, so the
pytest suite can assert on it and ``python -m eval.run_scenarios`` can print it
for a demonstration.
"""

from . import (
    call_switching,
    inaccessible_aed_reassignment,
    offline_recovery,
    snapshot_first_handoff,
)

SCENARIOS = (
    call_switching,
    inaccessible_aed_reassignment,
    offline_recovery,
    snapshot_first_handoff,
)

SCENARIOS_BY_NAME = {module.NAME: module for module in SCENARIOS}

__all__ = ["SCENARIOS", "SCENARIOS_BY_NAME"]
