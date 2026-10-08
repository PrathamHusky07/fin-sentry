"""
Loads and validates the scenario registry from scenarios.yml.

Validation runs at load time so a malformed scenario fails the test suite and the
gateway start, never a live run. The registry is read-only data: nothing in the
runner or the API edits it.
"""

from __future__ import annotations

from collections import Counter
from functools import cache
from pathlib import Path

import yaml
from pydantic import TypeAdapter

from finsentry.redteam.models import EVIDENCE_KEYS, Scenario

SCENARIOS_PATH = Path(__file__).parent / "scenarios.yml"

_ADAPTER: TypeAdapter[list[Scenario]] = TypeAdapter(list[Scenario])


class RegistryError(ValueError):
    """The scenario file is structurally valid YAML but breaks a registry rule."""


def parse_scenarios(raw: object) -> list[Scenario]:
    scenarios = _ADAPTER.validate_python(raw)
    _check_rules(scenarios)
    return scenarios


def _check_rules(scenarios: list[Scenario]) -> None:
    duplicates = [i for i, n in Counter(s.id for s in scenarios).items() if n > 1]
    if duplicates:
        raise RegistryError(f"duplicate scenario ids: {sorted(duplicates)}")
    for s in scenarios:
        unknown = set(s.required_evidence) - EVIDENCE_KEYS[s.executor]
        if unknown:
            raise RegistryError(
                f"{s.id} requires evidence its {s.executor} executor never emits: {sorted(unknown)}"
            )
        faithfulness_path = s.executor == "output_rails" and s.target_layer == "faithfulness"
        if s.mode == "judge_assisted" and not faithfulness_path:
            raise RegistryError(f"{s.id} is judge_assisted but is not the faithfulness path")
        if s.target_layer == "faithfulness" and s.mode != "judge_assisted":
            raise RegistryError(f"{s.id} targets faithfulness so it must be judge_assisted")
        if s.expected.layer is not None and s.expected.layer != s.target_layer:
            raise RegistryError(f"{s.id} expects a different layer than its target layer")


@cache
def load_scenarios(path: Path = SCENARIOS_PATH) -> tuple[Scenario, ...]:
    raw = yaml.safe_load(path.read_text())
    return tuple(parse_scenarios(raw))


def get_scenario(scenario_id: str) -> Scenario | None:
    return next((s for s in load_scenarios() if s.id == scenario_id), None)
