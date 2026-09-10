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
    _RAG_BUDGET,
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


# ---------------------------------------------------------------------------
# Defect 1: request-level breaker semantics (commit d3a-fix-1)
# ---------------------------------------------------------------------------


async def test_single_failed_request_increments_breaker_by_one_regardless_of_retries() -> None:
    """One request that retries 5 times on 500 produces exactly one failure increment.

    Invariant: each logical _call_downstream_rag produces at most one
    record_failure() call, regardless of how many internal retry attempts fired.
    Under pre-fix code this test fails because record_failure was called inside
    _attempt() on every retry.
    """
    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    mock_client = _make_mock_client(responses=[500])

    with (
        patch("finsentry.gateway.main.httpx.AsyncClient", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("finsentry.gateway.main._RAG_STOP", stop_after_attempt(5)),
    ):
        with pytest.raises(RetryError):
            await _call_downstream_rag(
                [{"role": "user", "content": "?"}],
                "http://fake-downstream",
                breaker,
            )

    assert breaker.failure_count == 1, (
        f"Expected 1 failure increment for one failed request, got {breaker.failure_count}"
    )


async def test_five_separate_failed_requests_trip_breaker() -> None:
    """Five separate failed requests increment the breaker five times and trip it.

    Invariant: the request-level (not per-retry) counting is what trips the
    breaker. Five consecutive _call_downstream_rag failures must open it.
    """
    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    mock_client = _make_mock_client(responses=[500])

    for _ in range(5):
        with (
            patch("finsentry.gateway.main.httpx.AsyncClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("finsentry.gateway.main._RAG_STOP", stop_after_attempt(1)),
        ):
            with pytest.raises(RetryError):
                await _call_downstream_rag(
                    [{"role": "user", "content": "?"}],
                    "http://fake-downstream",
                    breaker,
                )

    is_open, _ = await breaker.is_open()
    assert is_open, "Breaker must be OPEN after 5 separate failed requests"
    assert breaker.failure_count >= 5


async def test_successful_request_calls_record_success_once() -> None:
    """A request that fails on the first attempt and succeeds on the second calls
    record_success exactly once and record_failure zero times.

    Invariant: success on any attempt within the request => exactly one record_success(),
    and record_failure() is never called for that request.
    """
    from unittest.mock import patch as _patch

    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    mock_client = _make_mock_client(responses=[500, 200])

    success_mock = AsyncMock(wraps=breaker.record_success)
    failure_mock = AsyncMock(wraps=breaker.record_failure)

    with (
        patch("finsentry.gateway.main.httpx.AsyncClient", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("finsentry.gateway.main._RAG_STOP", stop_after_attempt(3)),
        _patch.object(breaker, "record_success", success_mock),
        _patch.object(breaker, "record_failure", failure_mock),
    ):
        result = await _call_downstream_rag(
            [{"role": "user", "content": "?"}],
            "http://fake-downstream",
            breaker,
        )

    assert result == "ok"
    assert success_mock.call_count == 1, "record_success must be called exactly once on success"
    assert failure_mock.call_count == 0, "record_failure must not be called when request succeeds"


# ---------------------------------------------------------------------------
# Defect 2: absolute deadline and per-attempt budget (commit d3a-fix-2)
# ---------------------------------------------------------------------------


async def test_absolute_deadline_holds_under_hung_downstream() -> None:
    """Per-attempt httpx timeout is bounded by the remaining budget, never None.

    Invariant: no _call_downstream_rag invocation may block indefinitely because
    of a hung downstream. The timeout passed to httpx.AsyncClient is
    min(_ATTEMPT_CAP, remaining_budget), which is always a finite value <= budget.
    Under pre-fix code, httpx.Timeout(None) was passed and no per-attempt bound
    existed; this test would fail because None is not <= budget.
    """
    assert _RAG_BUDGET == 20.0, "Production budget constant must be 20 seconds"

    captured_timeouts: list[httpx.Timeout] = []

    def make_client(*args: object, timeout: object = None, **kwargs: object) -> MagicMock:
        if isinstance(timeout, httpx.Timeout):
            captured_timeouts.append(timeout)
        base = _make_mock_client(exc=httpx.TimeoutException("hung"))
        return base

    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

    with (
        patch("finsentry.gateway.main.httpx.AsyncClient", side_effect=make_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("finsentry.gateway.main._RAG_BUDGET", 0.1),
        patch("finsentry.gateway.main._RAG_STOP", stop_after_attempt(2)),
    ):
        with pytest.raises(RetryError):
            await _call_downstream_rag(
                [{"role": "user", "content": "?"}],
                "http://fake-downstream",
                breaker,
            )

    assert len(captured_timeouts) > 0, "At least one httpx.Timeout must have been captured"
    for t in captured_timeouts:
        assert t.read is not None, "Timeout must be finite, not None"
        assert t.read <= 0.1 + 0.01, (
            f"Per-attempt timeout {t.read} must be bounded by the 0.1s test budget"
        )


async def test_backoff_does_not_start_if_it_would_exceed_deadline() -> None:
    """When remaining budget < base backoff, the sleep is capped at remaining, not skipped entirely.

    Invariant: the retry loop must not sleep for the full base backoff when the budget
    is nearly exhausted. _budget_wait clips the sleep to min(base, remaining), so the
    sleep value is << the 0.5s minimum exponential backoff when remaining is small.
    """
    fake_time = [0.0]

    def fake_mono() -> float:
        return fake_time[0]

    # Each attempt burns 95% of the 100ms budget so the remaining budget for the
    # backoff sleep is only 5ms -- well below the 0.5s minimum exponential wait.
    call_count = [0]

    def make_client(*args: object, timeout: object = None, **kwargs: object) -> MagicMock:
        async def fake_post(*a: object, **kw: object) -> object:
            call_count[0] += 1
            fake_time[0] += 0.095  # consume 95ms of budget per attempt
            raise httpx.TimeoutException("timeout")

        client = MagicMock()
        client.post = fake_post
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

    with (
        patch("finsentry.gateway.main.time.monotonic", fake_mono),
        patch("finsentry.gateway.main.httpx.AsyncClient", side_effect=make_client),
        patch("finsentry.gateway.main._RAG_BUDGET", 0.1),
        patch("asyncio.sleep", fake_sleep),
        patch("finsentry.gateway.main._RAG_STOP", stop_after_attempt(3)),
    ):
        with pytest.raises(RetryError):
            await _call_downstream_rag(
                [{"role": "user", "content": "?"}],
                "http://fake-downstream",
                breaker,
            )

    assert len(sleep_calls) > 0, "At least one backoff sleep must have been issued"
    for s in sleep_calls:
        assert s < 0.5, (
            f"Sleep {s}s must be clipped below 0.5s (minimum base backoff) "
            "when remaining budget is 0.005s"
        )


async def test_two_slow_attempts_do_not_exceed_deadline() -> None:
    """When attempt 1 consumes most of the budget, attempt 2 receives a smaller timeout.

    Invariant: each attempt's httpx timeout is min(_ATTEMPT_CAP, remaining), so a
    slow first attempt automatically shrinks the second attempt's timeout to the
    leftover budget. Under pre-fix code both attempts received Timeout(None), meaning
    the second attempt could run for an unbounded additional 20+ seconds.
    """
    fake_time = [0.0]

    def fake_mono() -> float:
        return fake_time[0]

    captured_timeouts: list[httpx.Timeout] = []
    call_count = [0]

    def make_client(*args: object, timeout: object = None, **kwargs: object) -> MagicMock:
        if isinstance(timeout, httpx.Timeout):
            captured_timeouts.append(timeout)

        async def fake_post(*a: object, **kw: object) -> object:
            call_count[0] += 1
            if call_count[0] == 1:
                fake_time[0] += 0.07  # attempt 1 consumes 70% of 0.1s budget
            raise httpx.TimeoutException("timeout")

        client = MagicMock()
        client.post = fake_post
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

    with (
        patch("finsentry.gateway.main.time.monotonic", fake_mono),
        patch("finsentry.gateway.main.httpx.AsyncClient", side_effect=make_client),
        patch("finsentry.gateway.main._RAG_BUDGET", 0.1),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("finsentry.gateway.main._RAG_STOP", stop_after_attempt(2)),
    ):
        with pytest.raises(RetryError):
            await _call_downstream_rag(
                [{"role": "user", "content": "?"}],
                "http://fake-downstream",
                breaker,
            )

    assert len(captured_timeouts) == 2, f"Expected 2 attempts, got {len(captured_timeouts)}"
    t1 = captured_timeouts[0].read
    t2 = captured_timeouts[1].read
    assert t1 is not None and t2 is not None, "Both timeouts must be finite"
    assert t2 < t1, (
        f"Attempt 2 timeout ({t2}s) must be smaller than attempt 1 ({t1}s) "
        "because attempt 1 consumed 70% of the budget"
    )
    assert t1 <= 0.1 + 0.001, f"Attempt 1 timeout {t1} must be bounded by 0.1s budget"
    assert t2 <= 0.1 + 0.001, f"Attempt 2 timeout {t2} must also be bounded"


async def test_read_error_is_treated_as_transport_failure() -> None:
    """httpx.ReadError (a TransportError subclass) retries and on success records no failure.

    Invariant: the broadened (httpx.TimeoutException, httpx.TransportError) catch
    in _attempt covers read-side failures. A ReadError on attempt 1 followed by a
    200 on attempt 2 produces a successful result with failure_count == 0.
    """
    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    success_body = {"choices": [{"message": {"content": "ok"}}]}
    call_count = [0]

    async def fake_post(*args: object, **kwargs: object) -> MagicMock:
        call_count[0] += 1
        if call_count[0] == 1:
            raise httpx.ReadError("connection reset")
        r = MagicMock()
        r.status_code = 200
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
        patch("finsentry.gateway.main._RAG_STOP", stop_after_attempt(3)),
    ):
        result = await _call_downstream_rag(
            [{"role": "user", "content": "?"}],
            "http://fake-downstream",
            breaker,
        )

    assert result == "ok", "ReadError on attempt 1 must retry; attempt 2 must succeed"
    assert call_count[0] == 2, f"Expected 2 attempts (1 ReadError + 1 success), got {call_count[0]}"
    assert breaker.failure_count == 0, "Successful request must leave failure_count at 0"


# ---------------------------------------------------------------------------
# Defect 3: OPEN-state idempotence (commit d3a-fix-3)
# ---------------------------------------------------------------------------


async def test_late_failure_after_breaker_opens_does_not_reset_opened_at() -> None:
    """A record_failure call arriving after the breaker is already OPEN must not
    reset _opened_at and thereby extend the recovery window.

    Invariant: the 30-second recovery window is anchored to the first transition
    to OPEN, not to the last failure. Under pre-fix code, _opened_at was
    unconditionally overwritten on every record_failure call that crossed the
    threshold, so late in-flight requests arriving after the breaker opened
    could silently push back the recovery by several seconds.
    """
    fake_now = [0.0]

    def clock() -> float:
        return fake_now[0]

    breaker = AsyncCircuitBreaker(failure_threshold=5, recovery_timeout=30.0, _now=clock)

    # Trip the breaker at t=0.
    for _ in range(5):
        await breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    opened_at_first = breaker._opened_at

    # Advance the injected clock: a late in-flight request arrives 5 seconds later.
    fake_now[0] = 5.0

    # This extra failure must NOT overwrite _opened_at.
    await breaker.record_failure()

    assert breaker._opened_at == opened_at_first, (
        f"_opened_at changed from {opened_at_first} to {breaker._opened_at}; "
        "a late failure must not reset the recovery window"
    )

    # The breaker must still open after recovery_timeout elapses from the original open time.
    fake_now[0] = 31.0  # 31s from the original open
    is_open, _ = await breaker.is_open()
    assert not is_open, "Breaker must recover after 30s from first open, not from last failure"
