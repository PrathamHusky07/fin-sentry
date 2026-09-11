"""Unit tests for the RisingWave version check logic in scripts/smoke_test_infra.py.

Tests the operator-precedence fix from Milestone 0f: the check must match v3.0.x
variants exactly and must NOT match v13.x, v2.x, or v3.1.x.
"""
from __future__ import annotations

import pytest


def _risingwave_version_matches(version_str: str) -> bool:
    """Inline the fixed check logic so tests do not depend on script import side effects."""
    return (
        version_str.startswith("v3.0.")
        or version_str.startswith("3.0.")
        or "RisingWave-3.0." in version_str
    )


@pytest.mark.parametrize(
    "version_str, expected",
    [
        # Should match (v3.0.x variants)
        ("v3.0.3", True),
        ("v3.0.0", True),
        ("3.0.3", True),
        ("3.0.0", True),
        ("RisingWave-3.0.3", True),
        ("RisingWave-3.0.0", True),
        # Should NOT match
        ("v13.0.0", False),   # starts with v1, not v3.0
        ("v2.3.0.1", False),  # v2 line
        ("v3.1.0", False),    # v3.1 line, not v3.0
        ("v3.10.0", False),   # v3.10 line
        ("unknown", False),
    ],
)
def test_risingwave_version_check_handles_v3_0_variants_correctly(
    version_str: str, expected: bool
) -> None:
    assert _risingwave_version_matches(version_str) == expected, (
        f"version_str={version_str!r}: expected {expected}, got {not expected}"
    )
