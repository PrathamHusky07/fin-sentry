from __future__ import annotations

import logging
from typing import Any

from finsentry.rails.base import Rail, RailDecision

# Llama Guard 3 1B in bfloat16 is the deployed hazard classifier. The 8B NF4
# alternative was evaluated (Meta's English F1 0.939 vs 1B's 0.899; FPR 0.040
# vs 0.090) but requires CUDA-backed NF4 quantization that is out of scope
# under the project's zero-cost constraint. See
# docs/adr/002-llama-guard-model-choice.md for the full decision record.
_MODEL_ID = "meta-llama/Llama-Guard-3-1B"

log = logging.getLogger(__name__)

# Module-level cache for the tokenizer and model.
_tokenizer: Any = None
_model: Any = None


def _get_model() -> tuple[Any, Any]:
    global _tokenizer, _model
    if _tokenizer is None or _model is None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        _tokenizer = AutoTokenizer.from_pretrained(_MODEL_ID)
        _model = AutoModelForCausalLM.from_pretrained(
            _MODEL_ID,
            dtype=torch.bfloat16,
            device_map="auto",
        )
        _model.eval()
        log.info("Llama Guard loaded: %s", _model.config._name_or_path)
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
    """Input rail: classifies requests against Meta's hazard taxonomy via Llama Guard 3 1B.

    Uses meta-llama/Llama-Guard-3-1B in bfloat16. The 8B NF4 alternative
    achieves F1 0.939 vs 1B's 0.899 on Meta's English hazard benchmark and
    halves the false-positive rate, but requires CUDA-backed NF4 quantization
    that is out of scope under the zero-cost constraint. See
    docs/adr/002-llama-guard-model-choice.md.
    """

    name = "llama-guard-3"
    layer = "input"

    def check(self, content: str, context: dict[str, Any]) -> RailDecision:
        tokenizer, model = _get_model()
        import torch

        chat = [{"role": "user", "content": content}]
        # apply_chat_template with the Llama Guard chat template formats the
        # prompt with the full hazard taxonomy preamble.
        # return_dict=True returns a BatchEncoding so ** unpacking works cleanly
        # in generate(). Positional tensor passing broke in transformers 5.x
        # when apply_chat_template began returning BatchEncoding by default.
        inputs = tokenizer.apply_chat_template(
            chat,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(model.device)

        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=20,
                pad_token_id=tokenizer.eos_token_id,
            )

        # Decode only the newly generated tokens (skip the prompt).
        generated = tokenizer.decode(
            output[0][inputs["input_ids"].shape[-1] :],
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
