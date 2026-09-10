from __future__ import annotations

import logging
import re
from typing import Any

from finsentry.rails.base import Rail, RailDecision

# Llama Guard 3 1B in bfloat16 is the deployed hazard classifier. The 8B NF4
# alternative was evaluated (Meta's English F1 0.939 vs 1B's 0.899; FPR 0.040
# vs 0.090) but requires CUDA-backed NF4 quantization that is out of scope
# under the project's zero-cost constraint. See
# docs/adr/002-llama-guard-model-choice.md for the full decision record.
_MODEL_ID = "meta-llama/Llama-Guard-3-1B"

log = logging.getLogger(__name__)

# Grammar-strict regexes for Llama Guard 3's "unsafe" verdict format.
# _CATEGORY_LINE_RE validates the complete second line: one or more S<N> tokens
# (N in 1–13) comma-separated with no trailing comma, leading/trailing garbage,
# or interstitial whitespace. _TOKEN_RE validates each individual token after
# splitting on "," as a defence-in-depth check.
_CATEGORY_LINE_RE: re.Pattern[str] = re.compile(
    r"^S([1-9]|1[0-3])(,S([1-9]|1[0-3]))*$"
)
_TOKEN_RE: re.Pattern[str] = re.compile(r"^S([1-9]|1[0-3])$")

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


def _parse_verdict(decoded_output: str) -> RailDecision:
    """Parse Llama Guard output into a RailDecision.

    Accepts exactly two forms after .strip():
    - The literal string "safe" → pass.
    - Two lines where line 1 is exactly "unsafe" (no suffix) and line 2
      matches _CATEGORY_LINE_RE: one or more S<N> tokens (N in 1–13),
      comma-separated, no trailing comma, no interstitial garbage → block.

    Anything else, including "unsafe" with no category, an out-of-range
    category, garbage appended to "unsafe", or concatenated tokens without
    a comma separator, is treated as an error (fail-closed). A lenient
    fallback to "safe" would allow a hallucinating model to bypass the rail.
    """
    text = decoded_output.strip()
    if text == "safe":
        return RailDecision(
            outcome="pass",
            reason="no hazard detected",
            details={"verdict": "safe"},
        )
    lines = text.splitlines()
    if len(lines) == 2 and lines[0] == "unsafe":
        cat_line = lines[1].strip()
        if _CATEGORY_LINE_RE.match(cat_line):
            tokens = cat_line.split(",")
            if all(_TOKEN_RE.match(t) for t in tokens):
                return RailDecision(
                    outcome="block",
                    reason=f"content policy violation: {', '.join(tokens)}",
                    details={"verdict": "unsafe", "categories": tokens},
                )
    log.warning(
        "Llama Guard produced malformed output; failing closed. raw=%r",
        decoded_output[:200],
    )
    return RailDecision(
        outcome="error",
        reason="malformed model output",
        details={"verdict": "malformed", "raw_output": decoded_output[:200]},
    )


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

        # Content-blocks form: Llama Guard 3's chat template uses Jinja
        # selectattr('type', 'equalto', 'text') to extract user content.
        # A plain string is iterated character-by-character; selectattr matches
        # nothing and the conversation section renders empty. Verified
        # empirically via scripts/diagnostic_llama_guard_prompt_variants.py.
        chat = [{"role": "user", "content": [{"type": "text", "text": content}]}]
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
        return _parse_verdict(generated)
