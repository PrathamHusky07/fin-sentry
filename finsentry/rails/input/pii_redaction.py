from __future__ import annotations

from typing import Any

from presidio_anonymizer.entities import OperatorConfig

from finsentry.rails.base import Rail, RailDecision

_CONFIDENCE_THRESHOLD = 0.7  # Default Presidio threshold is 0.5; 0.7 prevents
# false-positive redaction of SEC filing identifiers (CIK numbers, CUSIP codes,
# routing numbers in financial tables) that pattern recognizers can misfire on.

# Input-rail recognizer allowlist — five pattern-based types only.
# PERSON (SpacyRecognizer / NER) is excluded deliberately: in the finance
# domain, person names in queries are almost always public figures (executives,
# analysts, board members) legitimately present in SEC filings. Redacting
# "Tim Cook, CEO of Apple" would silently break RAG retrieval on the corpus.
# Real PII in this domain is account numbers and tax IDs, which the five
# pattern recognizers below catch reliably.
_ENTITY_TYPES = [
    "US_SSN",
    "CREDIT_CARD",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_BANK_NUMBER",
    "IBAN_CODE",
]

# Built once at import time — same config for every call.
_OPERATORS: dict[str, Any] = {
    entity: OperatorConfig("replace", {"new_value": f"<REDACTED_{entity}>"})
    for entity in _ENTITY_TYPES
}

# Retrieval-rail entity types and operators.
# SEC-context policy (empirically derived from 200-chunk diagnostic):
#   KEEP:   DATE_TIME, LOCATION, PERSON, NRP, ORGANIZATION, URL,
#           PHONE_NUMBER (0.4 score in sample; IR numbers are public),
#           US_BANK_NUMBER, IBAN_CODE (false-positive-heavy on financial IDs),
#           US_DRIVER_LICENSE (fires on "Q2", "Q3", CIK numbers at score 0.237;
#             all below 0.7 threshold — effectively zero valid hits in corpus)
#   REDACT: EMAIL_ADDRESS, US_SSN, CREDIT_CARD, IP_ADDRESS,
#           CRYPTO (wallet addresses)
# Full rationale in scripts/diagnostic_presidio_sec_context.py.
_RETRIEVAL_ENTITY_TYPES = [
    "EMAIL_ADDRESS",
    "US_SSN",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "CRYPTO",
]

_RETRIEVAL_OPERATORS: dict[str, Any] = {
    entity: OperatorConfig("replace", {"new_value": f"<REDACTED_{entity}>"})
    for entity in _RETRIEVAL_ENTITY_TYPES
}

# Module-level cache for the analyzer and anonymizer.
_analyzer: Any = None
_anonymizer: Any = None


def _get_analyzer() -> Any:
    global _analyzer
    if _analyzer is None:
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_analyzer.predefined_recognizers import (
            CreditCardRecognizer,
            EmailRecognizer,
            IbanRecognizer,
            PhoneRecognizer,
            UsBankRecognizer,
            UsSsnRecognizer,
        )

        registry = RecognizerRegistry()
        registry.add_recognizer(UsSsnRecognizer())
        registry.add_recognizer(CreditCardRecognizer())
        registry.add_recognizer(EmailRecognizer())
        registry.add_recognizer(PhoneRecognizer())
        registry.add_recognizer(UsBankRecognizer())
        registry.add_recognizer(IbanRecognizer())
        # Every recognizer above is pattern-based (regex); none needs spaCy
        # NER. Left unconfigured, AnalyzerEngine falls back to its own
        # default NlpEngineProvider, which wants en_core_web_lg and downloads
        # it at request time if missing -- en_core_web_sm (already baked
        # into the gateway image) is pinned explicitly here instead.
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
        ).create_engine()
        _analyzer = AnalyzerEngine(nlp_engine=nlp_engine, registry=registry)
    return _analyzer


def _get_anonymizer() -> Any:
    global _anonymizer
    if _anonymizer is None:
        from presidio_anonymizer import AnonymizerEngine

        _anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]
    return _anonymizer


class PiiRedactionRail(Rail):
    """Input rail: detects and masks PII in the user message before forwarding.

    Outcome is 'sanitize' (not 'block') — the request is allowed through with
    the PII replaced by <REDACTED_TYPE> placeholders. The downstream model never
    sees the original values.
    """

    name = "pii-redaction"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        analyzer = _get_analyzer()
        anonymizer = _get_anonymizer()

        results = analyzer.analyze(
            text=content,
            entities=_ENTITY_TYPES,
            language="en",
            score_threshold=_CONFIDENCE_THRESHOLD,
        )

        if not results:
            return RailDecision(outcome="pass", reason="no PII detected", details={})

        anonymized = anonymizer.anonymize(
            text=content,
            analyzer_results=results,
            operators=_OPERATORS,
        )

        detected = sorted({r.entity_type for r in results})
        return RailDecision(
            outcome="sanitize",
            reason="PII detected and redacted",
            details={
                "pii_entities": detected,
                "sanitized_content": anonymized.text,
            },
        )
