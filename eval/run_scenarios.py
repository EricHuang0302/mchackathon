"""Run the synthetic incident scenarios and print their deterministic output.

    python -m eval.run_scenarios
    python -m eval.run_scenarios offline_recovery

Output is stable JSON: the same command on another machine produces the same
bytes, so a diff is a real behaviour change rather than noise.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .scenarios import SCENARIOS, SCENARIOS_BY_NAME


def run_all(names: Sequence[str] | None = None) -> dict[str, object]:
    selected = (
        [SCENARIOS_BY_NAME[name] for name in names] if names else list(SCENARIOS)
    )
    return {module.NAME: module.run() for module in selected}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenario",
        nargs="*",
        choices=sorted(SCENARIOS_BY_NAME) or None,
        help="scenario names to run; defaults to all",
    )
    parser.add_argument(
        "--indent", type=int, default=2, help="JSON indent (0 for compact)"
    )
    args = parser.parse_args(argv)

    results = run_all(args.scenario or None)
    indent = args.indent or None
    print(json.dumps(results, indent=indent, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
