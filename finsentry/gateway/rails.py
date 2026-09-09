from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import yaml

from finsentry.rails.base import Rail, RailDecision
from finsentry.telemetry import get_tracer

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "rails.yml"
_COLANG_PATH = Path(__file__).parent / "colang"


def _decision_to_outcome(
    decision: RailDecision,
    on_failure_mode: str = "closed",
) -> object:
    """Translate a RailDecision into a NeMo RailOutcome.

    Imported at call time because nemoguardrails may not be available in all
    environments. Return type is object to avoid importing RailOutcome at
    module level.
    """
    from nemoguardrails.actions.rail_outcome import RailOutcome, TransformTarget

    if decision.outcome == "pass":
        return RailOutcome.allow(reason=decision.reason, metadata=decision.details)
    if decision.outcome == "block":
        return RailOutcome.block(reason=decision.reason, metadata=decision.details)
    if decision.outcome == "sanitize":
        sanitized = str(decision.details.get("sanitized_content", ""))
        return RailOutcome.transform(
            [(TransformTarget.USER_MESSAGE, sanitized)],
            reason=decision.reason,
            metadata=decision.details,
        )
    # outcome == "error" or anything unexpected
    if on_failure_mode == "open":
        return RailOutcome.allow(
            reason=f"rail_error (fail-open): {decision.reason}",
            metadata={"rail_error": True, "fail_open": True, **decision.details},
        )
    return RailOutcome.failure(
        reason=f"rail_error: {decision.reason}",
        metadata={"rail_error": True, **decision.details},
    )


def _exception_to_outcome(
    rail_name: str,
    exc: Exception,
    on_failure_mode: str = "closed",
) -> object:
    """Translate an uncaught rail exception into a NeMo RailOutcome."""
    from nemoguardrails.actions.rail_outcome import RailOutcome

    if on_failure_mode == "open":
        log.warning("Rail %s failed (fail-open): %s", rail_name, exc)
        return RailOutcome.allow(
            reason=f"rail_error (fail-open): {exc}",
            metadata={"rail_error": True, "fail_open": True},
        )
    log.error("Rail %s failed (fail-closed): %s", rail_name, exc)
    return RailOutcome.failure(
        reason=f"rail_error: {exc}",
        metadata={"rail_error": True},
    )


class InputRailsAdapter:
    """Routes input-rail checks through NeMo's check_async so Colang drives
    sequencing and explain() fills with real audit data.
    """

    def __init__(
        self,
        rails: list[Rail],
        config_path: Path = _CONFIG_PATH,
        colang_path: Path = _COLANG_PATH,
    ) -> None:
        self._rails = rails
        self._on_failure: dict[str, str] = {}

        if config_path.exists():
            raw: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
            for name, settings in (raw.get("rails", {}).get("input", {})).items():
                self._on_failure[name] = settings.get("on_failure", "closed")

        self._tracer = get_tracer("finsentry.rails.input")
        self._nemo = self._init_nemo(colang_path, rails)

    def _init_nemo(self, colang_path: Path, rails: list[Rail]) -> object | None:
        try:
            from nemoguardrails import LLMRails, RailsConfig
            from nemoguardrails.actions.actions import action

            config = RailsConfig.from_path(str(colang_path))
            nemo = LLMRails(config)

            on_failure = self._on_failure
            tracer = self._tracer

            def _find_rail(name: str) -> Rail | None:
                return next((r for r in rails if r.name == name), None)

            @action(name="prompt_guard_2_check", execute_async=True)  # type: ignore[untyped-decorator]
            async def prompt_guard_2_check(context: dict[str, Any]) -> object:
                user_message = str(context.get("user_message") or "")
                rail = _find_rail("prompt-guard-2")
                if rail is None:
                    from nemoguardrails.actions.rail_outcome import RailOutcome

                    return RailOutcome.allow(reason="rail not configured")
                with tracer.start_as_current_span("rail.prompt-guard-2.check") as span:
                    span.set_attribute("rail.name", "prompt-guard-2")
                    span.set_attribute("rail.layer", "input")
                    t0 = time.monotonic()
                    try:
                        decision = await asyncio.to_thread(rail.check, user_message, {})
                    except Exception as exc:
                        latency_ms = round((time.monotonic() - t0) * 1000, 2)
                        span.set_attribute("rail.decision", "error")
                        span.set_attribute("rail.latency_ms", latency_ms)
                        return _exception_to_outcome(
                            "prompt-guard-2", exc, on_failure.get("prompt-guard-2", "closed")
                        )
                    latency_ms = round((time.monotonic() - t0) * 1000, 2)
                    span.set_attribute("rail.decision", decision.outcome)
                    span.set_attribute("rail.latency_ms", latency_ms)
                    if "injection_probability" in decision.details:
                        span.set_attribute(
                            "rail.confidence", decision.details["injection_probability"]
                        )
                return _decision_to_outcome(
                    decision, on_failure.get("prompt-guard-2", "closed")
                )

            @action(name="pii_redact", execute_async=True)  # type: ignore[untyped-decorator]
            async def pii_redact(context: dict[str, Any]) -> object:
                user_message = str(context.get("user_message") or "")
                rail = _find_rail("pii-redaction")
                if rail is None:
                    from nemoguardrails.actions.rail_outcome import RailOutcome

                    return RailOutcome.allow(reason="rail not configured")
                with tracer.start_as_current_span("rail.pii-redaction.check") as span:
                    span.set_attribute("rail.name", "pii-redaction")
                    span.set_attribute("rail.layer", "input")
                    t0 = time.monotonic()
                    try:
                        decision = await asyncio.to_thread(rail.check, user_message, {})
                    except Exception as exc:
                        latency_ms = round((time.monotonic() - t0) * 1000, 2)
                        span.set_attribute("rail.decision", "error")
                        span.set_attribute("rail.latency_ms", latency_ms)
                        return _exception_to_outcome(
                            "pii-redaction", exc, on_failure.get("pii-redaction", "closed")
                        )
                    latency_ms = round((time.monotonic() - t0) * 1000, 2)
                    span.set_attribute("rail.decision", decision.outcome)
                    span.set_attribute("rail.latency_ms", latency_ms)
                return _decision_to_outcome(
                    decision, on_failure.get("pii-redaction", "closed")
                )

            @action(name="llama_guard_3_check", execute_async=True)  # type: ignore[untyped-decorator]
            async def llama_guard_3_check(context: dict[str, Any]) -> object:
                user_message = str(context.get("user_message") or "")
                rail = _find_rail("llama-guard-3")
                if rail is None:
                    from nemoguardrails.actions.rail_outcome import RailOutcome

                    return RailOutcome.allow(reason="rail not configured")
                with tracer.start_as_current_span("rail.llama-guard-3.check") as span:
                    span.set_attribute("rail.name", "llama-guard-3")
                    span.set_attribute("rail.layer", "input")
                    t0 = time.monotonic()
                    try:
                        decision = await asyncio.to_thread(rail.check, user_message, {})
                    except Exception as exc:
                        latency_ms = round((time.monotonic() - t0) * 1000, 2)
                        span.set_attribute("rail.decision", "error")
                        span.set_attribute("rail.latency_ms", latency_ms)
                        return _exception_to_outcome(
                            "llama-guard-3", exc, on_failure.get("llama-guard-3", "closed")
                        )
                    latency_ms = round((time.monotonic() - t0) * 1000, 2)
                    span.set_attribute("rail.decision", decision.outcome)
                    span.set_attribute("rail.latency_ms", latency_ms)
                return _decision_to_outcome(
                    decision, on_failure.get("llama-guard-3", "closed")
                )

            nemo.register_action(prompt_guard_2_check, name="prompt_guard_2_check")
            nemo.register_action(pii_redact, name="pii_redact")
            nemo.register_action(llama_guard_3_check, name="llama_guard_3_check")

            result: object = nemo
            return result
        except Exception as exc:
            log.warning("NeMo init failed — audit surface unavailable: %s", exc)
            return None

    async def run(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, object, object]:
        """Route messages through NeMo check_async.

        Returns (content, RailStatus, ExplainInfo). On NeMo init failure the
        adapter falls back to passing the original user message through with a
        synthetic PASSED-equivalent.
        """
        if self._nemo is None:
            user_content = str(
                next((m["content"] for m in messages if m.get("role") == "user"), "")
            )
            from nemoguardrails.logging.explain import ExplainInfo
            from nemoguardrails.rails.llm.options import RailStatus

            return user_content, RailStatus.PASSED, ExplainInfo()

        try:
            from nemoguardrails.logging.explain import ExplainInfo
            from nemoguardrails.rails.llm.options import RailStatus, RailType

            nemo: Any = self._nemo
            result = await nemo.check_async(messages, rail_types=[RailType.INPUT])
            explain: ExplainInfo = nemo.explain()
            return result.content, result.status, explain
        except Exception as exc:
            log.error("NeMo check_async failed: %s", exc)
            user_content = str(
                next((m["content"] for m in messages if m.get("role") == "user"), "")
            )
            from nemoguardrails.logging.explain import ExplainInfo
            from nemoguardrails.rails.llm.options import RailStatus

            return user_content, RailStatus.PASSED, ExplainInfo()

    def get_nemo(self) -> object | None:
        """Return the underlying LLMRails instance for Day 7 MCP audit surface."""
        return self._nemo
