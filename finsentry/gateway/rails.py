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


class InputRailsAdapter:
    """Sequences input rails and registers them with NeMo for the audit surface.

    The adapter owns all sequencing logic in Python. NeMo is used for
    programmatic action registration and audit history (required by the MCP
    explain_guardrail_decision tool on Day 7), not for flow orchestration.
    Gateway routes call this adapter; they never call NeMo or individual
    rails directly.
    """

    def __init__(
        self,
        rails: list[Rail],
        config_path: Path = _CONFIG_PATH,
    ) -> None:
        self._rails = rails
        self._on_failure: dict[str, str] = {}

        if config_path.exists():
            raw: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
            for name, settings in (raw.get("rails", {}).get("input", {})).items():
                self._on_failure[name] = settings.get("on_failure", "closed")

        self._nemo = self._init_nemo(rails)
        self._tracer = get_tracer("finsentry.rails.input")

    def _init_nemo(self, rails: list[Rail]) -> object | None:
        try:
            from nemoguardrails import LLMRails, RailsConfig

            config = RailsConfig.from_content(yaml_content="models: []\n")
            nemo = LLMRails(config)
            for rail in rails:
                nemo.register_action(rail.check, name=f"{rail.name}.check")
            # nemo is Any (nemoguardrails has no stubs); cast to object so
            # the function's declared return type is satisfied under strict mypy.
            result: object = nemo
            return result
        except Exception as exc:
            log.warning("NeMo init failed — audit surface unavailable: %s", exc)
            return None

    async def run(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[RailDecision]]:
        """Run all input rails in sequence.

        Returns updated messages (PII may be redacted) and the ordered list of
        RailDecision objects. Stops after the first block or error outcome.
        """
        decisions: list[RailDecision] = []
        user_content: str = str(
            next((m["content"] for m in messages if m.get("role") == "user"), "")
        )

        for rail in self._rails:
            with self._tracer.start_as_current_span(f"rail.{rail.name}.check") as span:
                span.set_attribute("rail.name", rail.name)
                span.set_attribute("rail.layer", "input")
                t0 = time.monotonic()

                try:
                    decision = await asyncio.to_thread(rail.check, user_content, {})
                except Exception as exc:
                    decision = self._handle_error(rail.name, exc)

                latency_ms = round((time.monotonic() - t0) * 1000, 2)
                span.set_attribute("rail.decision", decision.outcome)
                span.set_attribute("rail.latency_ms", latency_ms)

            decisions.append(decision)

            if decision.outcome == "sanitize":
                sanitized: str = str(
                    decision.details.get("sanitized_content", user_content)
                )
                messages = [
                    {**m, "content": sanitized} if m.get("role") == "user" else m
                    for m in messages
                ]
                user_content = sanitized
            elif decision.outcome in ("block", "error"):
                break

        return messages, decisions

    def _handle_error(self, rail_name: str, exc: Exception) -> RailDecision:
        on_failure = self._on_failure.get(rail_name, "closed")
        if on_failure == "open":
            log.warning("Rail %s failed (fail-open): %s", rail_name, exc)
            return RailDecision(
                outcome="pass",
                reason=f"rail_error (fail-open): {exc}",
                details={"rail_error": str(exc), "fail_open": True},
            )
        log.error("Rail %s failed (fail-closed): %s", rail_name, exc)
        return RailDecision(
            outcome="error",
            reason=f"rail_error: {exc}",
            details={"rail_error": str(exc)},
        )
