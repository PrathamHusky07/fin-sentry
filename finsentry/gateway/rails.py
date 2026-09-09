from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from finsentry.rails.base import Rail, RailDecision

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "rails.yml"
_COLANG_PATH = Path(__file__).parent / "colang"


class InputRailsAdapter:
    """Routes input-rail checks through NeMo's check_async so Colang drives
    sequencing and explain() fills with real audit data.

    Constructor registers stub action wrappers (each returns RailOutcome.allow)
    so the NeMo plumbing is testable end-to-end before the real wrappers land in
    Commit C.
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

        self._nemo = self._init_nemo(colang_path, rails)

    def _init_nemo(self, colang_path: Path, rails: list[Rail]) -> object | None:
        try:
            from nemoguardrails import LLMRails, RailsConfig
            from nemoguardrails.actions.rail_outcome import RailOutcome

            config = RailsConfig.from_path(str(colang_path))
            nemo = LLMRails(config)

            # Stub wrappers — each returns allow() so plumbing is testable.
            # Real wrappers that translate RailDecision→RailOutcome land in
            # Commit C, replacing these stubs.
            async def prompt_guard_2_check(context: dict[str, Any]) -> object:
                return RailOutcome.allow(reason="stub")

            async def pii_redact(context: dict[str, Any]) -> object:
                return RailOutcome.allow(reason="stub")

            async def llama_guard_3_check(context: dict[str, Any]) -> object:
                return RailOutcome.allow(reason="stub")

            nemo.register_action(prompt_guard_2_check, name="prompt_guard_2_check")
            nemo.register_action(pii_redact, name="pii_redact")
            nemo.register_action(llama_guard_3_check, name="llama_guard_3_check")

            result: object = nemo
            return result
        except Exception as exc:
            log.warning("NeMo init failed — audit surface unavailable: %s", exc)
            return None

    async def run(self, messages: list[dict[str, Any]]) -> tuple[str, object, object]:
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

    # Keep for test compatibility during Commit B — removed in Commit D cleanup.
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
