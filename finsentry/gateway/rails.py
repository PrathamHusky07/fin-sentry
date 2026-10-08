from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import yaml

from finsentry.rails.base import Rail, RailDecision
from finsentry.telemetry import get_tracer

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "rails.yml"
_COLANG_PATH = Path(__file__).parent / "colang"

# Rails that failed closed during the check_async call in progress. NeMo folds a
# fail-closed rail error into an ordinary BLOCKED result, so the action wrappers
# record the failure here and run() tells the two apart. The list is created per
# call and shared with NeMo's tasks through the copied context.
_rail_failures: ContextVar[list[str] | None] = ContextVar("rail_failures", default=None)


def _record_closed_failure(rail_name: str) -> None:
    failures = _rail_failures.get()
    if failures is not None:
        failures.append(rail_name)


class AdapterUnavailableError(RuntimeError):
    """Raised when the NeMo engine fails at the infrastructure level.

    This is distinct from a policy block (BLOCKED status -> 403). Infrastructure
    failures propagate as exceptions so the gateway can return 503
    (enforcement unavailable) rather than 403 (policy block). Conflating the
    two would misrepresent infrastructure failures as user-policy violations.
    """


def _decision_to_outcome(
    decision: RailDecision,
    on_failure_mode: str = "closed",
    rail_name: str = "unknown",
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
    _record_closed_failure(rail_name)
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
    _record_closed_failure(rail_name)
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

    def _init_nemo(self, colang_path: Path, rails: list[Rail]) -> object:
        """Initialise the NeMo LLMRails instance and register action wrappers.

        Raises on failure. The constructor propagates the exception so FastAPI
        refuses to start rather than starting in a broken, fail-open state.
        """
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
                        # context carries NeMo runtime state; rails may consult it.
                        decision = await asyncio.to_thread(rail.check, user_message, context)
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
                    if "malicious_probability" in decision.details:
                        span.set_attribute(
                            "rail.confidence", decision.details["malicious_probability"]
                        )
                return _decision_to_outcome(
                    decision, on_failure.get("prompt-guard-2", "closed"), "prompt-guard-2"
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
                        # context carries NeMo runtime state; rails may consult it.
                        decision = await asyncio.to_thread(rail.check, user_message, context)
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
                    decision, on_failure.get("pii-redaction", "closed"), "pii-redaction"
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
                        # context carries NeMo runtime state; rails may consult it.
                        decision = await asyncio.to_thread(rail.check, user_message, context)
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
                    decision, on_failure.get("llama-guard-3", "closed"), "llama-guard-3"
                )

            nemo.register_action(prompt_guard_2_check, name="prompt_guard_2_check")
            nemo.register_action(pii_redact, name="pii_redact")
            nemo.register_action(llama_guard_3_check, name="llama_guard_3_check")

            result: object = nemo
            return result
        except Exception as exc:
            log.error(
                "NeMo init failed — refusing to start without enforcement: %s",
                exc,
                exc_info=True,
            )
            raise

    # NeMo engine failure is intentionally not converted to a RailStatus. Per-rail
    # fail-open is configured in config/rails.yml at the individual rail level and
    # applies to individual rail crashes. Engine-level failures (NeMo init,
    # check_async crash) propagate as exceptions so the gateway returns 503
    # (enforcement unavailable), never 403 (policy block). Conflating the two
    # would misrepresent infrastructure failures as user-policy violations.
    async def _check(self, nemo: Any, messages: list[dict[str, Any]]) -> Any:
        """One check_async call. A BLOCKED result caused by a rail that failed
        closed is an infrastructure failure, not a policy block, so it raises."""
        from nemoguardrails.rails.llm.options import RailStatus, RailType

        failures: list[str] = []
        token = _rail_failures.set(failures)
        try:
            result = await nemo.check_async(messages, rail_types=[RailType.INPUT])
        finally:
            _rail_failures.reset(token)
        if result.status == RailStatus.BLOCKED and failures:
            raise AdapterUnavailableError(f"input rail {failures[0]} failed closed")
        return result

    async def run(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], object, str | None, object]:
        """Route each user message through NeMo check_async independently.

        Returns (updated_messages, RailStatus, rail_name, ExplainInfo).
        updated_messages is the full conversation list with any per-message
        transformations applied. On BLOCKED, the original messages list is
        returned (the gateway returns 403 and does not forward). On PASSED,
        the working list is returned unchanged.
        rail_name is the name of the blocking rail on BLOCKED, None otherwise.
        Raises AdapterUnavailableError on NeMo engine failure or when a rail
        failed closed (an error in the rail, not a policy decision).

        Each user message is scanned as a single-turn call so NeMo's
        context["user_message"] is set correctly for every turn. A single
        check_async(messages) call only exposes the last user message to the
        rail actions; earlier turns in a multi-turn conversation would be skipped.
        """
        try:
            from nemoguardrails.logging.explain import ExplainInfo
            from nemoguardrails.rails.llm.options import RailStatus

            nemo: Any = self._nemo
            user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]

            if not user_indices:
                result = await self._check(nemo, messages)
                explain: ExplainInfo = nemo.explain()
                return messages, result.status, result.rail, explain

            working: list[dict[str, Any]] = [dict(m) for m in messages]
            last_explain: ExplainInfo = ExplainInfo()
            any_modified = False

            for idx in user_indices:
                user_content = str(working[idx].get("content", ""))
                result = await self._check(nemo, [{"role": "user", "content": user_content}])
                last_explain = nemo.explain()

                if result.status == RailStatus.BLOCKED:
                    return messages, result.status, result.rail, last_explain

                if result.status == RailStatus.MODIFIED:
                    working[idx]["content"] = result.content
                    any_modified = True

            final_status: object = RailStatus.MODIFIED if any_modified else RailStatus.PASSED
            return working, final_status, None, last_explain

        except AdapterUnavailableError:
            raise
        except Exception as exc:
            log.error("NeMo check_async failed: %s", exc, exc_info=True)
            raise AdapterUnavailableError(f"NeMo check_async failed: {exc}") from exc

    def get_nemo(self) -> object:
        """Return the underlying LLMRails instance for Day 7 MCP audit surface."""
        return self._nemo
