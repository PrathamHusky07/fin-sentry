"""
Tests for AsyncCircuitBreaker and the 20-second request budget.

All tests use mocks. No real network, model, or DB required.

Budget and backoff tests call _call_downstream_rag directly to avoid httpx
patching collisions with the test's own AsyncClient (used by ASGITransport).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from tenacity import RetryError, stop_after_attempt

from finsentry.gateway.circuit_breaker import AsyncCircuitBreaker, CircuitState
from finsentry.gateway.main import (
    _RAG_STOP,
    _RAG_WAIT,
    _call_downstream_rag,
)


def _make_mock_client(
    responses: list[int] | None = None,
    exc: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock async context manager that mimics httpx.AsyncClient."""
    call_idx = [0]
    resp_list = responses or [200]
    success_body = {"choices": [{"message": {"content": "ok"}}]}

    async def fake_post(*args: object, **kwargs: object) -> MagicMock:
        if exc is not None:
            raise exc
        r = MagicMock()
        r.status_code = resp_list[min(call_idx[0], len(resp_list) - 1)]
        call_idx[0] += 1
        r.json.return_value = success_body
        r.raise_for_status = MagicMock()
        return r

    client = MagicMock()
    client.post = fake_post
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# AsyncCircuitBreaker unit tests
# ---------------------------------------------------------------------------


async def test_breaker_trips_after_5_consecutive_failures() -> None:
    """Five consecutive record_failure calls trip the breaker; is_open returns True."""
    fake_now = [0.0]

    def clock() -> float:
        return fake_now[0]

    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0, _now=clock)

    for _ in range(4):
        await breaker.record_failure()
    is_open, _ = await breaker.is_open()
    assert not is_open, "Breaker must stay CLOSED before reaching threshold"

    await breaker.record_failure()  # 5th failure
    is_open, retry_after = await breaker.is_open()
    assert is_open
    assert breaker.state == CircuitState.OPEN
    assert retry_after > 0


async def test_breaker_recovers_after_30_seconds() -> None:
    """After recovery_timeout elapses, is_open() transitions breaker back to CLOSED."""
    fake_now = [0.0]

    def clock() -> float:
        return fake_now[0]

    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0, _now=clock)

    for _ in range(5):
        await breaker.record_failure()

    is_open, _ = await breaker.is_open()
    assert is_open

    fake_now[0] = 31.0  # advance virtual clock past recovery_timeout

    is_open, remaining = await breaker.is_open()
    assert not is_open
    assert remaining == 0.0
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0


async def test_400_response_does_not_increment_breaker() -> None:
    """Ten consecutive 400s from downstream leave the breaker failure counter at zero."""
    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="test")
    mock_client = _make_mock_client(responses=[400])

    with patch("finsentry.gateway.main.httpx.AsyncClient", return_value=mock_client):
        for _ in range(10):
            try:
                await _call_downstream_rag(
                    [{"role": "user", "content": "?"}],
                    "http://fake-downstream",
                    breaker,
                )
            except Exception:
                pass  # _NonRetryableError expected; only care about breaker state

    assert breaker.failure_count == 0
    is_open, _ = await breaker.is_open()
    assert not is_open


async def test_429_retries_but_does_not_increment_breaker() -> None:
    """Three 429s then a 200: breaker counter stays at 0 and retries occurred."""
    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="test")
    call_count = [0]
    responses = [429, 429, 429, 200]
    success_body = {"choices": [{"message": {"content": "ok"}}]}

    async def fake_post(*args: object, **kwargs: object) -> MagicMock:
        r = MagicMock()
        r.status_code = responses[min(call_count[0], len(responses) - 1)]
        call_count[0] += 1
        r.json.return_value = success_body
        r.raise_for_status = MagicMock()
        return r

    client = MagicMock()
    client.post = fake_post
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("finsentry.gateway.main.httpx.AsyncClient", return_value=client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await _call_downstream_rag(
            [{"role": "user", "content": "?"}],
            "http://fake-downstream",
            breaker,
        )

    assert result == "ok"
    assert call_count[0] == 4  # 3 rate-limited retries + 1 success
    assert breaker.failure_count == 0
    is_open, _ = await breaker.is_open()
    assert not is_open


async def test_total_request_budget_20_seconds() -> None:
    """When every attempt fails, budget exhaustion produces RetryError (504 in endpoint).

    The test patches _RAG_STOP to stop_after_attempt(2) for speed; it separately
    asserts that the production constant is stop_after_delay(20). This decomposes
    the budget claim into: (a) production config uses 20-second delay, and (b)
    when tenacity stops, the failure produces RetryError which the endpoint maps to 504.
    """
    # (a) Verify the production configuration value.
    assert hasattr(_RAG_STOP, "max_delay"), "_RAG_STOP must be a stop_after_delay instance"
    assert _RAG_STOP.max_delay == 20  # type: ignore[union-attr]

    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    attempt_count = [0]

    async def fake_post(*args: object, **kwargs: object) -> object:
        attempt_count[0] += 1
        raise httpx.TimeoutException("timeout")

    client = MagicMock()
    client.post = fake_post
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    # (b) Patch stop to 2 attempts so the test runs in milliseconds, not 20 seconds.
    with (
        patch("finsentry.gateway.main.httpx.AsyncClient", return_value=client),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("finsentry.gateway.main._RAG_STOP", stop_after_attempt(2)),
    ):
        with pytest.raises(RetryError):
            await _call_downstream_rag(
                [{"role": "user", "content": "?"}],
                "http://fake-downstream",
                breaker,
            )

    assert attempt_count[0] == 2, f"Expected 2 attempts before stop, got {attempt_count[0]}"


async def test_retry_exponential_backoff_bounded_by_budget() -> None:
    """Sleep values from tenacity stay within [min=0.5, max=4] bounds."""
    # Verify production wait config
    assert _RAG_WAIT.multiplier == 0.5  # type: ignore[union-attr]
    assert _RAG_WAIT.min == 0.5  # type: ignore[union-attr]
    assert _RAG_WAIT.max == 4.0  # type: ignore[union-attr]

    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    sleep_calls: list[float] = []

    async def capture_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    async def fake_post(*args: object, **kwargs: object) -> object:
        raise httpx.TimeoutException("timeout")

    client = MagicMock()
    client.post = fake_post
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    # Stop after 4 attempts to collect a backoff sequence without real delay.
    with (
        patch("finsentry.gateway.main.httpx.AsyncClient", return_value=client),
        patch("asyncio.sleep", capture_sleep),
        patch("finsentry.gateway.main._RAG_STOP", stop_after_attempt(4)),
    ):
        with pytest.raises(RetryError):
            await _call_downstream_rag(
                [{"role": "user", "content": "?"}],
                "http://fake-downstream",
                breaker,
            )

    assert len(sleep_calls) > 0, "Tenacity must issue at least one sleep between retries"
    for s in sleep_calls:
        assert 0.5 <= s <= 4.0, f"Sleep {s} is outside configured bounds [0.5, 4.0]"
    if len(sleep_calls) >= 2:
        assert sleep_calls[1] >= sleep_calls[0], "Backoff must be non-decreasing"
