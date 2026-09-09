from __future__ import annotations

import logging
from typing import Any

from finsentry.rails.base import Rail, RailDecision

_MODEL_ID = "meta-llama/Llama-Prompt-Guard-2-86M"

# Class index 1 is the malicious/injection class per Meta's model card.
# As of transformers 5.16 and the current shipped model config, id2label falls
# back to LABEL_0/LABEL_1 rather than semantic BENIGN/MALICIOUS names. We
# identify the malicious class by label suffix ("_1") so the code is correct
# regardless of whether Meta ever fixes the shipped config. See
# docs/build-log.md 2026-09-09 diagnostic checkpoint.
_MALICIOUS_INDEX = 1
_MALICIOUS_THRESHOLD = 0.5  # Meta's published default for the malicious class

log = logging.getLogger(__name__)

# Module-level model cache. Loaded once on first call to _get_pipeline().
# fp32 on CPU: DeBERTa-v3 disentangled attention has known numerical drift on
# some MPS/PyTorch builds that can flip borderline cases. CPU fp32
# hits the 20-50 ms latency budget on M5 Pro for an 86M-parameter classifier.
_pipeline: Any = None


def _get_pipeline() -> Any:
    global _pipeline
    if _pipeline is None:
        from transformers import pipeline

        _pipeline = pipeline(
            "text-classification",
            model=_MODEL_ID,
            device="cpu",
            torch_dtype="float32",
        )
        log.debug("Prompt Guard 2 id2label: %s", _pipeline.model.config.id2label)
    return _pipeline


def _extract_malicious_probability(scores: list[dict[str, Any]]) -> float:
    """Return the malicious-class probability from a top_k=None pipeline result.

    Handles both runtime label taxonomies:
    - Current fallback: LABEL_0 (benign) / LABEL_1 (malicious) -- label ends with "_1"
    - Semantic (if Meta fixes shipped config): BENIGN / MALICIOUS -- matches case-insensitively

    With top_k=None the pipeline returns scores for all classes, so the
    malicious entry is always present in the list regardless of which class won.
    """
    for entry in scores:
        label = str(entry.get("label", ""))
        if label.upper() == "MALICIOUS" or label.endswith("_1"):
            return float(entry.get("score", 0.0))
    return 0.0


class PromptGuard2Rail(Rail):
    """Input rail: malicious prompt detection via Llama Prompt Guard 2 86M.

    Prompt Guard 2 is a binary classifier: class index 0 is benign, class
    index 1 is malicious/injection. The pipeline is called with top_k=None to
    get scores for both classes, then _extract_malicious_probability pulls the
    class-1 score regardless of whether id2label uses semantic names
    (BENIGN/MALICIOUS) or the generic fallback (LABEL_0/LABEL_1).
    """

    name = "prompt-guard-2"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        pipe = _get_pipeline()
        # top_k=None returns all class scores: [[{label, score}, ...]] for a
        # single string input (outer list is batch dimension, inner is classes).
        result = pipe(content, truncation=True, max_length=512, top_k=None)
        scores: list[dict[str, Any]] = result[0] if isinstance(result, list) else result
        malicious_probability = _extract_malicious_probability(scores)

        if malicious_probability >= _MALICIOUS_THRESHOLD:
            return RailDecision(
                outcome="block",
                reason="malicious prompt detected",
                details={
                    "malicious_probability": malicious_probability,
                    "threshold": _MALICIOUS_THRESHOLD,
                },
            )
        return RailDecision(
            outcome="pass",
            reason="no malicious prompt detected",
            details={
                "malicious_probability": malicious_probability,
                "threshold": _MALICIOUS_THRESHOLD,
            },
        )
