from __future__ import annotations

from typing import Any

from finsentry.gateway.rails import InputRailsAdapter
from finsentry.rails.base import Rail, RailDecision

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _PassRail(Rail):
    name = "test-pass"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        return RailDecision(outcome="pass", reason="ok")


class _BlockRail(Rail):
    name = "test-block"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        return RailDecision(outcome="block", reason="blocked by test rail")


class _SanitizeRail(Rail):
    name = "test-sanitize"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        return RailDecision(
            outcome="sanitize",
            reason="redacted",
            details={"sanitized_content": content.replace("SECRET", "<REDACTED>")},
        )


class _CrashRail(Rail):
    name = "test-crash"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        raise RuntimeError("rail machinery unavailable")


# ---------------------------------------------------------------------------
# Adapter infrastructure tests
# ---------------------------------------------------------------------------

async def test_adapter_empty_rails_passes_messages_through() -> None:
    adapter = InputRailsAdapter(rails=[])
    messages = [{"role": "user", "content": "hello"}]
    out_messages, decisions = await adapter.run(messages)
    assert out_messages == messages
    assert decisions == []


async def test_adapter_pass_rail_returns_pass_decision() -> None:
    adapter = InputRailsAdapter(rails=[_PassRail()])
    messages = [{"role": "user", "content": "what is revenue?"}]
    _, decisions = await adapter.run(messages)
    assert len(decisions) == 1
    assert decisions[0].outcome == "pass"


async def test_adapter_block_rail_returns_block_and_stops() -> None:
    adapter = InputRailsAdapter(rails=[_BlockRail(), _PassRail()])
    messages = [{"role": "user", "content": "bad input"}]
    _, decisions = await adapter.run(messages)
    # Only one decision: block rail fired, pass rail was skipped.
    assert len(decisions) == 1
    assert decisions[0].outcome == "block"


async def test_adapter_sanitize_rail_updates_user_content() -> None:
    adapter = InputRailsAdapter(rails=[_SanitizeRail()])
    messages = [{"role": "user", "content": "my SECRET is here"}]
    out_messages, decisions = await adapter.run(messages)
    assert decisions[0].outcome == "sanitize"
    assert out_messages[0]["content"] == "my <REDACTED> is here"


async def test_adapter_sanitized_content_seen_by_subsequent_rails() -> None:
    """Sanitize updates the content flowing into the next rail."""

    class _RecordRail(Rail):
        name = "test-record"
        layer = "input"
        seen: str = ""

        def check(self, content: str, context: dict[str, Any]) -> RailDecision:
            _RecordRail.seen = content
            return RailDecision(outcome="pass", reason="ok")

    adapter = InputRailsAdapter(rails=[_SanitizeRail(), _RecordRail()])
    await adapter.run([{"role": "user", "content": "my SECRET is here"}])
    assert _RecordRail.seen == "my <REDACTED> is here"


# ---------------------------------------------------------------------------
# Fail-closed / fail-open tests (no actual rail models needed)
# ---------------------------------------------------------------------------

async def test_crash_rail_fail_closed_returns_error() -> None:
    adapter = InputRailsAdapter(rails=[_CrashRail()])
    _, decisions = await adapter.run([{"role": "user", "content": "x"}])
    assert decisions[0].outcome == "error"
    assert "rail_error" in decisions[0].details


async def test_crash_rail_fail_open_returns_pass_with_warning() -> None:
    # Override on_failure for test-crash to "open" by patching the adapter config.
    adapter = InputRailsAdapter(rails=[_CrashRail()])
    adapter._on_failure["test-crash"] = "open"
    _, decisions = await adapter.run([{"role": "user", "content": "x"}])
    assert decisions[0].outcome == "pass"
    assert decisions[0].details.get("fail_open") is True


async def test_error_outcome_stops_subsequent_rails() -> None:
    adapter = InputRailsAdapter(rails=[_CrashRail(), _PassRail()])
    _, decisions = await adapter.run([{"role": "user", "content": "x"}])
    assert len(decisions) == 1
    assert decisions[0].outcome == "error"
