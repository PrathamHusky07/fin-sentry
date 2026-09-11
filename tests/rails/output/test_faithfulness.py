"""Phase 5 mock-based tests for FaithfulnessRail."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from finsentry.rails.output.faithfulness import (
    FaithfulnessRail,
    Mode,
    _GeminiSkipError,
    _strip_json_fences,
)

# --- helpers ---


def _make_chunk(chunk_id: str, text: str = "Revenue was $94.9B.") -> Any:
    c = MagicMock()
    c.chunk_id = chunk_id
    c.text = text
    return c


def _make_rail(threshold: float = 0.7) -> FaithfulnessRail:
    rail = FaithfulnessRail.__new__(FaithfulnessRail)
    rail._model_name = "gemini-3.6-flash"
    rail._threshold = threshold
    rail._per_call_timeout = 8.0
    rail._enabled = True
    rail._mode = "developer"
    rail._client = MagicMock()
    return rail


def _mock_generate(responses: list[tuple[str, int, int]]) -> Any:
    """Return an AsyncMock that yields successive (text, in_tok, out_tok) tuples."""
    call_iter = iter(responses)

    async def _side_effect(prompt: str) -> tuple[str, int, int]:
        return next(call_iter)

    return _side_effect


# --- test cases ---


@pytest.mark.asyncio
async def test_faithfulness_disabled_without_api_key_passes_with_skipped_status() -> None:
    rail = FaithfulnessRail(mode="disabled", model_name="gemini-3.6-flash")
    decision = await rail.check("Some answer.", [_make_chunk("c1")])
    assert decision.outcome == "pass"
    assert decision.details["faithfulness_status"] == "skipped_no_key"


@pytest.mark.asyncio
async def test_vertex_mode_missing_project_falls_back_to_disabled() -> None:
    with patch("google.genai.Client"):
        rail = FaithfulnessRail(mode="vertex", model_name="gemini-3.6-flash", project=None)
    assert not rail._enabled
    assert rail._mode == "disabled"
    decision = await rail.check("Some answer.", [_make_chunk("c1")])
    assert decision.outcome == "pass"
    assert decision.details["faithfulness_status"] == "skipped_no_key"


@pytest.mark.asyncio
async def test_developer_mode_missing_api_key_falls_back_to_disabled() -> None:
    with patch("google.genai.Client"):
        rail = FaithfulnessRail(mode="developer", model_name="gemini-3.6-flash", api_key=None)
    assert not rail._enabled
    assert rail._mode == "disabled"
    decision = await rail.check("Some answer.", [_make_chunk("c1")])
    assert decision.outcome == "pass"
    assert decision.details["faithfulness_status"] == "skipped_no_key"


@pytest.mark.asyncio
async def test_invalid_mode_falls_back_to_disabled_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from typing import cast as typing_cast

    with patch("google.genai.Client"):
        with caplog.at_level(logging.ERROR, logger="finsentry.rails.output.faithfulness"):
            rail = FaithfulnessRail(
                mode=typing_cast(Mode, "invalid_mode"),
                model_name="gemini-3.6-flash",
            )
    assert not rail._enabled
    assert rail._mode == "disabled"
    assert any("invalid mode" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_faithfulness_all_claims_supported_passes() -> None:
    rail = _make_rail()
    claims_response = json.dumps(["Revenue was $94.9B.", "iPhone drove sales."])
    verdicts = [
        (json.dumps({"verdict": "yes", "rationale": "context confirms"}), 50, 20),
        (json.dumps({"verdict": "yes", "rationale": "context confirms"}), 50, 20),
    ]
    responses: list[tuple[str, int, int]] = [(claims_response, 100, 30)] + verdicts

    with patch.object(rail, "_generate", side_effect=_mock_generate(responses)):
        decision = await rail.check("Revenue was $94.9B. iPhone drove sales.", [_make_chunk("c1")])

    assert decision.outcome == "pass"
    assert decision.details["score"] == 1.0
    assert decision.details["faithfulness_status"] == "passed"


@pytest.mark.asyncio
async def test_faithfulness_partial_support_blocks() -> None:
    rail = _make_rail(threshold=0.7)
    claims_response = json.dumps(["Claim A.", "Claim B.", "Claim C.", "Claim D."])
    verdicts = [
        (json.dumps({"verdict": "yes", "rationale": "ok"}), 50, 20),
        (json.dumps({"verdict": "no", "rationale": "not in context"}), 50, 20),
        (json.dumps({"verdict": "no", "rationale": "not in context"}), 50, 20),
        (json.dumps({"verdict": "no", "rationale": "not in context"}), 50, 20),
    ]
    responses: list[tuple[str, int, int]] = [(claims_response, 100, 30)] + verdicts

    with patch.object(rail, "_generate", side_effect=_mock_generate(responses)):
        decision = await rail.check("Claim A. Claim B. Claim C. Claim D.", [_make_chunk("c1")])

    assert decision.outcome == "block"
    assert decision.reason == "low_faithfulness"
    # 1/4 = 0.25 < 0.7
    assert abs(decision.details["score"] - 0.25) < 0.001


@pytest.mark.asyncio
async def test_faithfulness_exactly_at_threshold_passes() -> None:
    # 7 supported / 10 total = 0.7 exactly -> PASS (>= boundary)
    rail = _make_rail(threshold=0.7)
    claims = [f"Claim {i}." for i in range(10)]
    claims_response = json.dumps(claims)
    verdicts: list[tuple[str, int, int]] = []
    for i in range(10):
        v = "yes" if i < 7 else "no"
        verdicts.append((json.dumps({"verdict": v, "rationale": "ok"}), 50, 20))
    responses: list[tuple[str, int, int]] = [(claims_response, 200, 40)] + verdicts

    with patch.object(rail, "_generate", side_effect=_mock_generate(responses)):
        decision = await rail.check(" ".join(claims), [_make_chunk("c1")])

    assert decision.outcome == "pass"
    assert abs(decision.details["score"] - 0.7) < 0.001


@pytest.mark.asyncio
async def test_faithfulness_just_below_threshold_blocks() -> None:
    # 6 supported / 10 total = 0.6 < 0.7 -> BLOCK
    rail = _make_rail(threshold=0.7)
    claims = [f"Claim {i}." for i in range(10)]
    claims_response = json.dumps(claims)
    verdicts: list[tuple[str, int, int]] = []
    for i in range(10):
        v = "yes" if i < 6 else "no"
        verdicts.append((json.dumps({"verdict": v, "rationale": "ok"}), 50, 20))
    responses: list[tuple[str, int, int]] = [(claims_response, 200, 40)] + verdicts

    with patch.object(rail, "_generate", side_effect=_mock_generate(responses)):
        decision = await rail.check(" ".join(claims), [_make_chunk("c1")])

    assert decision.outcome == "block"
    assert abs(decision.details["score"] - 0.6) < 0.001


@pytest.mark.asyncio
async def test_faithfulness_zero_claims_scores_1_0() -> None:
    rail = _make_rail()
    claims_response = json.dumps([])
    responses: list[tuple[str, int, int]] = [(claims_response, 50, 10)]

    with patch.object(rail, "_generate", side_effect=_mock_generate(responses)):
        decision = await rail.check("", [_make_chunk("c1")])

    assert decision.outcome == "pass"
    assert decision.details["score"] == 1.0
    assert decision.details["faithfulness_status"] == "passed"


@pytest.mark.asyncio
async def test_faithfulness_rate_limit_fails_open() -> None:
    rail = _make_rail()

    async def _raise_rate_limit(prompt: str) -> tuple[str, int, int]:
        raise _GeminiSkipError("skipped_rate_limit", {})

    with patch.object(rail, "_generate", side_effect=_raise_rate_limit):
        decision = await rail.check("Some answer.", [_make_chunk("c1")])

    assert decision.outcome == "pass"
    assert decision.details["faithfulness_status"] == "skipped_rate_limit"


@pytest.mark.asyncio
async def test_faithfulness_timeout_fails_open() -> None:
    rail = _make_rail()
    # Set an expired deadline so the timeout fires before calling Gemini
    rail._per_call_timeout = 0.001

    async def _slow(prompt: str) -> tuple[str, int, int]:
        await asyncio.sleep(5)
        return ("", 0, 0)

    with patch.object(rail, "_generate", side_effect=_slow):
        decision = await rail.check("Some answer.", [_make_chunk("c1")])

    assert decision.outcome == "pass"
    assert "skipped_timeout" in decision.details.get("faithfulness_status", "")


@pytest.mark.asyncio
async def test_faithfulness_upstream_500_fails_open() -> None:
    rail = _make_rail()

    async def _raise_500(prompt: str) -> tuple[str, int, int]:
        raise _GeminiSkipError("skipped_upstream_error", {})

    with patch.object(rail, "_generate", side_effect=_raise_500):
        decision = await rail.check("Some answer.", [_make_chunk("c1")])

    assert decision.outcome == "pass"
    assert decision.details["faithfulness_status"] == "skipped_upstream_error"


@pytest.mark.asyncio
async def test_faithfulness_auth_error_fails_open_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rail = _make_rail()

    async def _raise_auth(prompt: str) -> tuple[str, int, int]:
        raise _GeminiSkipError("skipped_auth_error", {})

    with patch.object(rail, "_generate", side_effect=_raise_auth):
        decision = await rail.check("Some answer.", [_make_chunk("c1")])

    assert decision.outcome == "pass"
    assert decision.details["faithfulness_status"] == "skipped_auth_error"


@pytest.mark.asyncio
async def test_faithfulness_uses_filtered_chunks_not_raw() -> None:
    # Verify: only chunk text from the passed-in list appears in context sent to Gemini.
    rail = _make_rail()
    captured_prompts: list[str] = []

    async def _capture(prompt: str) -> tuple[str, int, int]:
        captured_prompts.append(prompt)
        if len(captured_prompts) == 1:
            return (json.dumps(["Single claim."]), 50, 20)
        return (json.dumps({"verdict": "yes", "rationale": "ok"}), 50, 20)

    kept_chunk = _make_chunk("kept-id", "Revenue was $94.9B.")

    # Only pass kept_chunk (simulating retrieval rail having dropped the other chunk)
    with patch.object(rail, "_generate", side_effect=_capture):
        await rail.check("Revenue was $94.9B.", [kept_chunk])

    # The context in the verification prompt must NOT contain the dropped chunk's text
    verification_prompt = captured_prompts[1] if len(captured_prompts) > 1 else ""
    assert "DROPPED TEXT SHOULD NOT APPEAR" not in verification_prompt
    assert "kept-id" in verification_prompt


@pytest.mark.asyncio
async def test_faithfulness_bounds_claim_count_at_10() -> None:
    rail = _make_rail()
    # Claim extraction returns 15 claims; only first 10 should be verified
    fifteen_claims = [f"Claim {i}." for i in range(15)]
    claims_response = json.dumps(fifteen_claims)

    verify_count = 0

    async def _count_calls(prompt: str) -> tuple[str, int, int]:
        nonlocal verify_count
        if verify_count == 0:
            verify_count += 1
            return (claims_response, 100, 30)
        verify_count += 1
        return (json.dumps({"verdict": "yes", "rationale": "ok"}), 50, 20)

    with patch.object(rail, "_generate", side_effect=_count_calls):
        decision = await rail.check("Many claims.", [_make_chunk("c1")])

    # 1 extraction call + 10 verification calls (not 15)
    assert verify_count == 11
    assert len(decision.details.get("supported_claims", [])) + len(
        decision.details.get("unsupported_claims", [])
    ) == 10


@pytest.mark.asyncio
async def test_faithfulness_records_gemini_token_usage() -> None:
    rail = _make_rail()
    claims_response = json.dumps(["Single claim."])
    responses: list[tuple[str, int, int]] = [
        (claims_response, 123, 45),  # extraction call
        (json.dumps({"verdict": "yes", "rationale": "ok"}), 67, 22),  # verification
    ]

    with patch.object(rail, "_generate", side_effect=_mock_generate(responses)):
        decision = await rail.check("Single claim.", [_make_chunk("c1")])

    assert decision.details["input_tokens"] == 123 + 67
    assert decision.details["output_tokens"] == 45 + 22
    assert decision.details["gemini_calls"] == 2


# --- _strip_json_fences unit tests ---


def test_strip_json_fences_plain_json_unchanged() -> None:
    raw = '{"verdict": "yes", "rationale": "matches"}'
    assert _strip_json_fences(raw) == raw


def test_strip_json_fences_strips_json_code_fence() -> None:
    raw = '```json\n{"verdict": "yes", "rationale": "ok"}\n```'
    assert _strip_json_fences(raw) == '{"verdict": "yes", "rationale": "ok"}'


def test_strip_json_fences_strips_plain_code_fence() -> None:
    raw = '```\n["claim A", "claim B"]\n```'
    assert _strip_json_fences(raw) == '["claim A", "claim B"]'


def test_strip_json_fences_multiline_array() -> None:
    raw = '```json\n[\n  "Claim 1.",\n  "Claim 2."\n]\n```'
    result = _strip_json_fences(raw)
    assert json.loads(result) == ["Claim 1.", "Claim 2."]


@pytest.mark.asyncio
async def test_faithfulness_handles_markdown_fenced_gemini_responses() -> None:
    """Gemini may wrap JSON in ```json ... ``` fences; verify claims are parsed correctly."""
    rail = _make_rail()
    # Claim extraction wrapped in markdown fence
    fenced_claims = '```json\n["Revenue was $94.9B."]\n```'
    # Verdict wrapped in markdown fence
    fenced_verdict = '```json\n{"verdict": "yes", "rationale": "context confirms"}\n```'
    responses: list[tuple[str, int, int]] = [
        (fenced_claims, 100, 30),
        (fenced_verdict, 50, 20),
    ]

    with patch.object(rail, "_generate", side_effect=_mock_generate(responses)):
        decision = await rail.check("Revenue was $94.9B.", [_make_chunk("c1")])

    assert decision.outcome == "pass"
    assert decision.details["score"] == 1.0
    assert decision.details["supported_claims"] == ["Revenue was $94.9B."]
