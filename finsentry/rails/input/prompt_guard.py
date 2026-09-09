from __future__ import annotations

from typing import Any

from finsentry.rails.base import Rail, RailDecision

_MODEL_ID = "meta-llama/Llama-Prompt-Guard-2-86M"
_MALICIOUS_LABEL = "MALICIOUS"
_MALICIOUS_THRESHOLD = 0.5  # Meta's published default for the malicious class

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
    return _pipeline


class PromptGuard2Rail(Rail):
    """Input rail: malicious prompt detection via Llama Prompt Guard 2 86M.

    Prompt Guard 2 uses binary BENIGN/MALICIOUS classification. The pipeline
    returns the probability for whichever label is on top; this class normalises
    to malicious_probability regardless of which label wins.
    """

    name = "prompt-guard-2"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        pipe = _get_pipeline()
        result = pipe(content, truncation=True, max_length=512)
        # result is a list of dicts: [{"label": "MALICIOUS"|"BENIGN", "score": float}]
        top: dict[str, Any] = result[0] if isinstance(result, list) else result
        label: str = str(top.get("label", "BENIGN"))
        score: float = float(top.get("score", 0.0))
        # Pipeline returns probability for the top label. Normalise to the
        # malicious probability regardless of which label comes out on top.
        malicious_probability = score if label == _MALICIOUS_LABEL else 1.0 - score

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
