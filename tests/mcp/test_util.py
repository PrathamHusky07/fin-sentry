from __future__ import annotations

import pytest

from finsentry.mcp._util import validate_limit


def test_validate_limit_accepts_in_bounds_value() -> None:
    validate_limit(1)
    validate_limit(500)
    validate_limit(50)


def test_validate_limit_rejects_zero_and_negative() -> None:
    with pytest.raises(ValueError, match="limit must be >= 1"):
        validate_limit(0)
    with pytest.raises(ValueError, match="limit must be >= 1"):
        validate_limit(-5)


def test_validate_limit_rejects_above_max() -> None:
    with pytest.raises(ValueError, match="limit must be <= 500"):
        validate_limit(501)
