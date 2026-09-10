"""
Schema enforcement rail: validates generated responses against RagAnswerResponse,
cross-checks every citation chunk_id against the set of retrieved chunk ids,
and enforces self-consistency between empty citations and confidence level.

Guardrails AI was evaluated but rejected due to hard transitive dependencies on
openai>=2.0 and litellm>=1.82.5. This rail implements equivalent validation using
pure Pydantic. See ADR 005.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from finsentry.rails.base import RailDecision
from finsentry.rails.output.schema import RagAnswerResponse


class SchemaEnforcementRail:
    """Validate and parse the downstream LLM's raw response string.

    Sequence (first block wins):
      1. JSON parse failure -> block malformed_json
      2. Pydantic schema validation failure -> block schema_violation
      3. Hallucinated citation chunk_id (not in retrieved set) -> block hallucinated_citation
      4. Empty citations with confidence != "low" -> block empty_citations_with_non_low_confidence
      5. All pass -> RailDecision(outcome="pass", details={"parsed": <RagAnswerResponse>})
    """

    name = "schema-enforcement"
    layer = "output"

    def check(
        self,
        response_text: str,
        retrieved_chunk_ids: set[str],
    ) -> RailDecision:
        # Step 1: JSON parse
        try:
            raw: Any = json.loads(response_text)
        except (json.JSONDecodeError, ValueError):
            return RailDecision(
                outcome="block",
                reason="malformed_json",
                details={"raw_snippet": response_text[:200]},
            )

        # Step 2: Pydantic schema validation
        try:
            parsed = RagAnswerResponse.model_validate(raw)
        except ValidationError as exc:
            errors = exc.errors()
            return RailDecision(
                outcome="block",
                reason="schema_violation",
                details={"validation_errors": errors},
            )

        # Step 3: Citation cross-check
        if parsed.citations:
            hallucinated = [
                c.chunk_id
                for c in parsed.citations
                if c.chunk_id not in retrieved_chunk_ids
            ]
            if hallucinated:
                valid_count = sum(
                    1 for c in parsed.citations if c.chunk_id in retrieved_chunk_ids
                )
                return RailDecision(
                    outcome="block",
                    reason="hallucinated_citation",
                    details={
                        "hallucinated_ids": hallucinated,
                        "surviving_ids_count": valid_count,
                    },
                )

        # Step 4: Self-consistency: empty citations must have confidence "low"
        if not parsed.citations and parsed.confidence != "low":
            return RailDecision(
                outcome="block",
                reason="empty_citations_with_non_low_confidence",
                details={"confidence": parsed.confidence},
            )

        return RailDecision(
            outcome="pass",
            reason="schema valid",
            details={"parsed": parsed},
        )
