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
            dtype="float32",
        )
        log.debug("Prompt Guard 2 id2label: %s", _pipeline.model.config.id2label)
    return _pipeline


def _extract_malicious_probability(scores: list[dict[str, Any]]) -> float:
    """Return the malicious-class probability from a top_k=None pipeline result.

    Matches by the LABEL_{_MALICIOUS_INDEX} string (authoritative selector) or
    by case-insensitive "MALICIOUS" (semantic-label compatibility path for if
    Meta ever fixes the shipped id2label config). Both taxonomies handled:
    - Current fallback: LABEL_0 (benign) / LABEL_1 (malicious)
    - Semantic (if Meta fixes shipped config): BENIGN / MALICIOUS

    With top_k=None the pipeline returns scores for all classes, so the
    malicious entry is always present in the list regardless of which class won.
    """
    target_index_label = f"LABEL_{_MALICIOUS_INDEX}"
    for entry in scores:
        label = str(entry.get("label", ""))
        if label == target_index_label or label.upper() == "MALICIOUS":
            return float(entry.get("score", 0.0))
    return 0.0


def _chunk_input(
    content: str,
    tokenizer: Any,
    max_tokens: int = 512,
    overlap: int = 0,
) -> list[str]:
    """Split content into chunks of at most max_tokens tokens.

    Tokenizes without special tokens, splits the token ID list into
    non-overlapping windows (overlap=0) of max_tokens each, then decodes each
    window back to text. Overlap=0 is correct here: empirical testing (see
    docs/build-log.md 2026-09-09 long-input diagnostic) showed no meaningful
    difference in detection probability between overlap=0 and overlap=50.

    Short-circuit: if the input fits in a single window, returns [content]
    without any tokenize/decode round-trip so short inputs carry no overhead.
    """
    token_ids: list[int] = tokenizer(content, add_special_tokens=False)["input_ids"]
    if len(token_ids) <= max_tokens:
        return [content]

    stride = max_tokens - overlap
    chunks: list[str] = []
    i = 0
    while i < len(token_ids):
        window = token_ids[i : i + max_tokens]
        chunks.append(tokenizer.decode(window, skip_special_tokens=True))
        i += stride
    return chunks


class PromptGuard2Rail(Rail):
    """Input rail: malicious prompt detection via Llama Prompt Guard 2 86M.

    Prompt Guard 2 is a binary classifier: class index 0 is benign, class
    index 1 is malicious/injection. The pipeline is called with top_k=None to
    get scores for both classes, then _extract_malicious_probability pulls the
    class-1 score regardless of whether id2label uses semantic names
    (BENIGN/MALICIOUS) or the generic fallback (LABEL_0/LABEL_1).

    Long inputs are split into 512-token chunks (Meta's context window) and
    classified in a single batch call. The maximum malicious probability across
    all chunks determines the outcome. This prevents the silent truncation bypass
    where a malicious instruction placed beyond token 512 was never seen by the
    classifier. Latency scales linearly with input length: short inputs (<=512
    tokens) take exactly one classifier call, matching prior behavior.
    """

    name = "prompt-guard-2"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        pipe = _get_pipeline()
        chunks = _chunk_input(content, pipe.tokenizer)

        # Batch call: top_k=None on a list of strings returns a list of
        # per-chunk score lists: [[{label, score}, ...], ...]. One inner list
        # per chunk. Batching avoids N sequential forward passes on multi-chunk
        # inputs and matches the transformers pipeline batch API contract.
        results: list[list[dict[str, Any]]] = pipe(chunks, truncation=False, top_k=None)

        max_chunk_probability = 0.0
        for chunk_scores in results:
            prob = _extract_malicious_probability(chunk_scores)
            if prob > max_chunk_probability:
                max_chunk_probability = prob

        malicious_probability = max_chunk_probability

        if malicious_probability >= _MALICIOUS_THRESHOLD:
            return RailDecision(
                outcome="block",
                reason="malicious prompt detected",
                details={
                    "malicious_probability": malicious_probability,
                    "threshold": _MALICIOUS_THRESHOLD,
                    "chunk_count": len(chunks),
                    "max_chunk_probability": malicious_probability,
                },
            )
        return RailDecision(
            outcome="pass",
            reason="no malicious prompt detected",
            details={
                "malicious_probability": malicious_probability,
                "threshold": _MALICIOUS_THRESHOLD,
                "chunk_count": len(chunks),
                "max_chunk_probability": malicious_probability,
            },
        )
