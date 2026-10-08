"""
Typed contracts for the Red Team Console: the scenario registry entries and the
vocabulary shared by the runner, the store and the API.

A scenario carries its EXPECTED outcome. The OBSERVED outcome is produced only by
an execution and lives in records.py. The two are never the same field, so a
scenario configured to be caught is not evidence that it was caught.

Observed outcomes (the five-state taxonomy):

- caught: a defense layer acted on the attack, with evidence of what it did.
- missed: the attack passed every relevant defense. A real finding, never hidden.
- evaluator_unavailable: a rail or judge could not run. Never a successful defense.
- execution_failed: the harness itself errored. Never a successful defense.
- inconclusive: the run completed but the evidence cannot support caught or missed.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

Category = Literal[
    "direct_injection",
    "hazard_content",
    "pii",
    "multi_stage",
    "indirect_injection",
    "output_schema",
    "regulated_phrase",
    "unsupported_claim",
    "citation_integrity",
]

# The defense layers a scenario can exercise. These are the `name` values the rails
# already use, so an acting layer in a result matches a block_rail in a trace.
Rail = Literal[
    "prompt-guard-2",
    "pii-redaction",
    "llama-guard-3",
    "retrieval-rail",
    "schema-enforcement",
    "regulated-phrases",
    "faithfulness",
]

Mode = Literal["deterministic", "judge_assisted"]
Severity = Literal["low", "medium", "high", "critical"]
Outcome = Literal["caught", "missed", "evaluator_unavailable", "execution_failed", "inconclusive"]
Expectation = Literal["met", "not_met", "not_assessable"]

# Every evidence key an executor can emit. A scenario may only require keys from its
# own executor's set, which the registry checks at load time.
EVIDENCE_KEYS: dict[str, frozenset[str]] = {
    "gateway_route": frozenset(
        {
            "gateway_status",
            "gateway_rail",
            "persisted_block_rail",
            "persisted_query_redacted",
            "trace_found",
        }
    ),
    "input_rails": frozenset({"rail_status", "redacted_entities", "leaked_entities"}),
    "retrieval_rail": frozenset({"attack_dropped", "drop_check", "control_kept"}),
    "output_rails": frozenset(
        {"schema_decision", "phrase_decision", "faithfulness_decision", "payload_verified"}
    ),
}


class GatewayInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    ticker: str | None = None


class InputRailsInput(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # Entity types the scenario puts in the text. All must be redacted to count as caught.
    expected_entities: list[str] = Field(min_length=1)


class BorrowSpec(BaseModel):
    ticker: str
    filing_type: Literal["10-K", "10-Q", "8-K"]


class ControlledChunk(BaseModel):
    """A retrieved chunk the harness builds. It borrows the identity of a real corpus
    chunk so the source-trust lookup is real, then replaces only the fields the
    scenario controls. role=control keeps the real text and proves the rail is not
    blocking everything."""

    role: Literal["attack", "control"]
    borrow_from: BorrowSpec
    text: str | None = Field(default=None, max_length=2000)
    source_url: str | None = None


class RetrievalInput(BaseModel):
    chunks: list[ControlledChunk]

    @model_validator(mode="after")
    def _needs_attack_and_control(self) -> RetrievalInput:
        roles = {c.role for c in self.chunks}
        if roles != {"attack", "control"}:
            raise ValueError("a retrieval scenario needs at least one attack and one control chunk")
        return self


class RetrievedStub(BaseModel):
    chunk_id: str
    text: str


class PayloadCheck(BaseModel):
    """Ground truth the harness verifies about its own payload, without asking the
    rail under test. A miss only counts when the payload really had the property."""

    kind: Literal[
        "citation_id_unretrieved",
        "quote_not_in_cited_chunk",
        "answer_contains",
        "answer_term_absent_from_context",
    ]
    value: str | None = None

    @model_validator(mode="after")
    def _value_when_needed(self) -> PayloadCheck:
        needs_value = self.kind in {"answer_contains", "answer_term_absent_from_context"}
        if needs_value and not self.value:
            raise ValueError(f"payload check {self.kind} needs a value")
        return self


class OutputRailsInput(BaseModel):
    raw_output: str = Field(min_length=1, max_length=4000)
    retrieved: list[RetrievedStub] = Field(min_length=1)
    payload_check: PayloadCheck


class Expected(BaseModel):
    outcome: Literal["caught", "missed"]
    layer: Rail | None = None
    check: str | None = None
    known_gap: bool = False
    rationale: str

    @model_validator(mode="after")
    def _consistent(self) -> Expected:
        if self.outcome == "caught" and self.layer is None:
            raise ValueError("an expected catch must name the layer that should act")
        if self.outcome == "missed" and self.layer is not None:
            raise ValueError("an expected miss names no acting layer")
        if self.known_gap and self.outcome != "missed":
            raise ValueError("a known gap is expected to be missed")
        return self


class _ScenarioBase(BaseModel):
    id: str = Field(pattern=r"^[A-Z]{2,4}-\d{3}$")
    version: int = Field(ge=1)
    title: str
    category: Category
    # The defense the scenario puts under test. For a known gap this is the nearest
    # layer that exists, not one that is claimed to cover the attack.
    target_layer: Rail
    description: str
    mode: Mode
    expected: Expected
    # Evidence keys that must be present before a catch is accepted.
    required_evidence: list[str]
    severity: Severity
    severity_rationale: str


class GatewayScenario(_ScenarioBase):
    executor: Literal["gateway_route"]
    input: GatewayInput


class InputRailsScenario(_ScenarioBase):
    executor: Literal["input_rails"]
    input: InputRailsInput


class RetrievalScenario(_ScenarioBase):
    executor: Literal["retrieval_rail"]
    input: RetrievalInput


class OutputRailsScenario(_ScenarioBase):
    executor: Literal["output_rails"]
    input: OutputRailsInput


Scenario = Annotated[
    GatewayScenario | InputRailsScenario | RetrievalScenario | OutputRailsScenario,
    Field(discriminator="executor"),
]
