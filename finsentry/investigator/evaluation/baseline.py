"""Record the always-abstain stub's score on the known-answer suite.

    python -m finsentry.investigator.evaluation.baseline

This validates the scoring, not an agent: the stub decides nothing, so its result shows that
the harness passes a correct abstention and fails a missing diagnosis. The file it writes is
the reference a future investigator version is compared against.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from finsentry.investigator.evaluation.runner import run_suite, write_result
from finsentry.investigator.stub import AlwaysAbstainInvestigator

OUTPUT = (
    Path(__file__).resolve().parents[3]
    / "docs/measurements/investigator/day11-0-stub-baseline.json"
)


def main() -> None:
    result = asyncio.run(run_suite(AlwaysAbstainInvestigator(), clock=lambda: 0.0))
    write_result(result, OUTPUT)
    print(f"wrote {OUTPUT.relative_to(OUTPUT.parents[3])}")
    print(result.summary)


if __name__ == "__main__":
    main()
