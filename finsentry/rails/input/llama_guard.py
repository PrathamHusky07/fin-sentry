from __future__ import annotations

from typing import Any

from finsentry.rails.base import Rail, RailDecision

_MODEL_ID = "meta-llama/Llama-Guard-3-8B"

# NF4 over int8: the memory budget for Day 5 (three frontier judges plus two
# input classifiers plus embeddings plus Docker plus OS) does not fit on 24 GB
# at int8. NF4 loses ~2 percentage points on Meta's hazard-taxonomy evaluation,
# invisible for finance-domain traffic where the hazard rate is under 1%, and
# buys ~4 GB of headroom.
_QUANTIZATION_CONFIG: dict[str, Any] = {
    "load_in_4bit": True,
    "bnb_4bit_quant_type": "nf4",
    "bnb_4bit_compute_dtype": "float16",
}

# Module-level cache for the tokenizer and model.
_tokenizer: Any = None
_model: Any = None


def _get_model() -> tuple[Any, Any]:
    global _tokenizer, _model
    if _tokenizer is None or _model is None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        quant_config = BitsAndBytesConfig(  # type: ignore[no-untyped-call]
            load_in_4bit=_QUANTIZATION_CONFIG["load_in_4bit"],
            bnb_4bit_quant_type=_QUANTIZATION_CONFIG["bnb_4bit_quant_type"],
            bnb_4bit_compute_dtype=getattr(torch, _QUANTIZATION_CONFIG["bnb_4bit_compute_dtype"]),
        )
        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_ID)
        _model = AutoModelForCausalLM.from_pretrained(
            _MODEL_ID,
            quantization_config=quant_config,
            device_map="auto",
        )
        _model.eval()
    return _tokenizer, _model


def _parse_verdict(output: str) -> tuple[str, str | None]:
    """Parse Llama Guard output into (verdict, hazard_category).

    Llama Guard 3 outputs either "safe" or "unsafe\nS<N>" where S<N> is
    a hazard category code from Meta's hazard taxonomy.
    """
    text = output.strip()
    if text.lower().startswith("unsafe"):
        lines = text.splitlines()
        category = lines[1].strip() if len(lines) > 1 else None
        return "unsafe", category
    return "safe", None


class LlamaGuard3Rail(Rail):
    """Input rail: classifies requests against Meta's hazard taxonomy via Llama Guard 3 8B NF4."""

    name = "llama-guard-3"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        tokenizer, model = _get_model()
        import torch

        chat = [{"role": "user", "content": content}]
        # apply_chat_template with the Llama Guard chat template formats the
        # prompt with the full hazard taxonomy preamble.
        input_ids = tokenizer.apply_chat_template(
            chat,
            return_tensors="pt",
        ).to(model.device)

        with torch.no_grad():
            output = model.generate(
                input_ids,
                max_new_tokens=20,
                pad_token_id=0,
            )

        # Decode only the newly generated tokens (skip the prompt).
        generated = tokenizer.decode(
            output[0][input_ids.shape[-1]:],
            skip_special_tokens=True,
        )
        verdict, category = _parse_verdict(generated)

        if verdict == "unsafe":
            details: dict[str, Any] = {"hazard_category": category or "unknown"}
            return RailDecision(
                outcome="block",
                reason=f"content policy violation: {category or 'unknown'}",
                details=details,
            )
        return RailDecision(
            outcome="pass",
            reason="no hazard detected",
            details={},
        )
