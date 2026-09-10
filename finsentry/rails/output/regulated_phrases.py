"""
Regulated-phrase blocklist: blocks generated answers containing language
that would violate FINRA Rule 2210 (communications standards) or SEC Rule 156
(investment company sales literature) or create legal exposure.

Runs on RagAnswerResponse.answer only, not on citations[].quote.
Rationale: the model may legally quote SEC filings that mention regulated
concepts (a fraud disclosure may contain "guaranteed returns"). Quoting
is not asserting.
"""
from __future__ import annotations

import re

from finsentry.rails.base import RailDecision

# Each entry: (compiled pattern, regulatory citation string)
_REGULATED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bguaranteed returns?\b", re.IGNORECASE), "FINRA Rule 2210"),
    (
        re.compile(r"\brisk[- ]free (?:investment|return|opportunity)\b", re.IGNORECASE),
        "FINRA Rule 2210",
    ),
    (re.compile(r"\bcan(?:'t| ?not) lose\b", re.IGNORECASE), "FINRA Rule 2210"),
    (
        re.compile(r"\binsider (?:tip|information|knowledge)\b", re.IGNORECASE),
        "SEC Rule 10b5-1",
    ),
    (re.compile(r"\bsure thing\b", re.IGNORECASE), "FINRA Rule 2210"),
    (re.compile(r"\bmoney[- ]back guarantee\b", re.IGNORECASE), "SEC Rule 156"),
)


class RegulatedPhraseRail:
    """Block generated answers containing FINRA/SEC-regulated language.

    check() runs against RagAnswerResponse.answer only, not citation quotes.
    On any match, returns a block decision listing all matched patterns,
    regulatory sources, and matched text spans.
    """

    name = "regulated-phrases"
    layer = "output"

    def check(self, answer_text: str) -> RailDecision:
        matched_patterns: list[str] = []
        regulatory_sources: list[str] = []
        matched_text: list[str] = []

        for pattern, regulation in _REGULATED_PATTERNS:
            for m in pattern.finditer(answer_text):
                matched_patterns.append(pattern.pattern)
                regulatory_sources.append(regulation)
                matched_text.append(m.group(0))

        if matched_patterns:
            return RailDecision(
                outcome="block",
                reason="regulated_phrase",
                details={
                    "matched_patterns": matched_patterns,
                    "regulatory_source": regulatory_sources,
                    "matched_text": matched_text,
                },
            )

        return RailDecision(outcome="pass", reason="no regulated phrases detected", details={})
