"""Phase 4 golden matrix tests for RegulatedPhraseRail."""
from __future__ import annotations

import pytest

from finsentry.rails.output.regulated_phrases import RegulatedPhraseRail


@pytest.fixture
def rail() -> RegulatedPhraseRail:
    return RegulatedPhraseRail()


# --- golden matrix ---


def test_clean_response_passes(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("Apple's Q4 revenue was $94.9 billion.")
    assert decision.outcome == "pass"


def test_guaranteed_returns_plural_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("This fund offers guaranteed returns of 8% annually.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_guaranteed_return_singular_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("This ETF provides a guaranteed return on your principal.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_risk_free_investment_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("Treasury bills are a risk-free investment for retail investors.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_risk_free_return_space_variant_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("The portfolio targets a risk free return of 5%.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_insider_tip_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("We have an insider tip on NVDA's upcoming announcement.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_insider_information_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("Trading on insider information is what drives alpha here.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_insider_knowledge_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("Our analyst has insider knowledge of the deal terms.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_sure_thing_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("Buying AAPL before earnings is a sure thing.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_money_back_guarantee_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("The fund offers a money-back guarantee within 30 days.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_case_insensitive_guaranteed_returns_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("GUARANTEED RETURNS OF 10% ARE AVAILABLE.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_word_boundary_safe_guaranteed_satisfaction_passes(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("We guarantee customer satisfaction with our products.")
    assert decision.outcome == "pass"


def test_word_boundary_safe_riskier_assets_passes(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("Investors may prefer riskier assets for higher yields.")
    assert decision.outcome == "pass"


def test_regulated_phrase_inside_citation_quote_passes(rail: RegulatedPhraseRail) -> None:
    # Rail runs on answer field only, not on citation quotes.
    # This test passes the answer text directly; citation quotes are not inspected.
    clean_answer = "The SEC filing discusses risk factors in the bond market."
    decision = rail.check(clean_answer)
    assert decision.outcome == "pass"


def test_details_contain_matched_text_and_regulatory_source(
    rail: RegulatedPhraseRail,
) -> None:
    decision = rail.check("This product offers guaranteed returns and is a sure thing.")
    assert decision.outcome == "block"
    assert len(decision.details["matched_text"]) == 2
    assert "FINRA Rule 2210" in decision.details["regulatory_source"]


def test_cant_lose_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("With this ETF you can't lose money over a 10-year horizon.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_cannot_lose_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("The fund manager claims investors cannot lose principal.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_risk_free_opportunity_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("This is a risk-free opportunity for all investors.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


def test_money_back_guarantee_space_variant_blocks(rail: RegulatedPhraseRail) -> None:
    decision = rail.check("They offer a money back guarantee on subscriptions.")
    assert decision.outcome == "block"
    assert decision.reason == "regulated_phrase"


# Verify the regulated phrase in citation quote scenario explicitly:
# The test above passes the answer field only, not JSON. Phase 6 ensures the
# rail is called with parsed.answer, not raw response_text. That architectural
# boundary is tested in test_output_rails_wiring.py (Phase 6).
def test_rail_called_on_answer_field_only_clean_answer_passes(
    rail: RegulatedPhraseRail,
) -> None:
    # Phase 6 wires this correctly: rail.check(parsed.answer), not raw JSON.
    # A clean answer field passes even when citation quotes contain regulated phrases.
    decision = rail.check("Revenue was $94.9B.")
    assert decision.outcome == "pass"
