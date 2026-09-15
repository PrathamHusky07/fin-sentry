#!/usr/bin/env python3
"""Measure memory and latency footprint for the three frontier judge models.

Loads each model in an isolated subprocess so RSS is measured cleanly without
interference from other models. Results are emitted as JSON to stdout and a
summary table to stderr.

Models measured (smallest to largest):
  1. HHEM-2.1-Open  (~440 MB)
  2. Patronus Lynx 8B  (~5-6 GB in 4-bit)
  3. Prometheus 2 7B   (~4-5 GB in 4-bit)

Usage:
    .venv/bin/python scripts/measure_frontier_models.py

Output:
    stdout: JSON object with per-model measurements
    stderr: human-readable summary table

Requires: psutil, transformers, torch. bitsandbytes or mlx-lm for 8B models.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

import psutil


# ---------------------------------------------------------------------------
# Per-model subprocess worker scripts
# These run inside isolated python processes so RSS is clean.
# ---------------------------------------------------------------------------

_HHEM_WORKER = """
import json, sys, time, os
import psutil

proc = psutil.Process(os.getpid())
baseline_rss = proc.memory_info().rss

start_load = time.monotonic()

from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

model_name = "vectara/hallucination_evaluation_model"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name)
model.eval()

load_latency_s = time.monotonic() - start_load
peak_rss_after_load = proc.memory_info().rss

# Warmup inference: one (premise, hypothesis) pair from the model card
pairs = [["The capital of France is Paris.", "France's capital is Paris."]]
start_inf = time.monotonic()
with torch.no_grad():
    inputs = tokenizer.batch_encode_plus(pairs, return_tensors="pt", truncation=True, max_length=512)
    logits = model(**inputs).logits.squeeze(dim=1)
    score = torch.sigmoid(logits).item()
inf_latency_s = time.monotonic() - start_inf

warmup_rss = proc.memory_info().rss

result = {
    "model": "HHEM-2.1-Open",
    "hub_id": model_name,
    "backend": "transformers",
    "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
    "rss_after_load_mb": round(peak_rss_after_load / 1024**2, 1),
    "rss_after_warmup_mb": round(warmup_rss / 1024**2, 1),
    "load_latency_s": round(load_latency_s, 2),
    "inf_latency_s": round(inf_latency_s, 4),
    "warmup_score": round(score, 4),
    "error": None,
}
json.dump(result, sys.stdout)
"""

_LYNX_WORKER = """
import json, sys, time, os
import psutil

proc = psutil.Process(os.getpid())
baseline_rss = proc.memory_info().rss

start_load = time.monotonic()

model_name = "PatronusAI/Llama-3-Patronus-Lynx-8B-Instruct"
backend_used = None
model = None
tokenizer = None

# Try bitsandbytes 4-bit first (works on CUDA; may fail on Apple Silicon)
try:
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    import torch

    bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name, quantization_config=bnb_config, device_map="auto"
    )
    backend_used = "bitsandbytes-4bit"
except Exception as bnb_exc:
    bnb_error = str(bnb_exc)[:200]
    # Try mlx-lm (Apple Silicon native)
    try:
        import mlx_lm
        model, tokenizer = mlx_lm.load(model_name)
        backend_used = "mlx-lm"
    except Exception as mlx_exc:
        # Try llama-cpp-python with GGUF quant
        try:
            from llama_cpp import Llama
            # Q4_K_M GGUF from PatronusAI's HuggingFace repo
            gguf_repo = "PatronusAI/Patronus-Lynx-8B-Instruct-Q4_K_M-GGUF"
            from huggingface_hub import hf_hub_download
            gguf_path = hf_hub_download(repo_id=gguf_repo, filename="Patronus-Lynx-8B-Instruct-Q4_K_M.gguf")
            model = Llama(model_path=gguf_path, n_ctx=2048, verbose=False)
            tokenizer = None
            backend_used = "llama-cpp-gguf"
        except Exception as gguf_exc:
            result = {
                "model": "Patronus-Lynx-8B",
                "hub_id": model_name,
                "backend": None,
                "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
                "rss_after_load_mb": None,
                "rss_after_warmup_mb": None,
                "load_latency_s": None,
                "inf_latency_s": None,
                "warmup_score": None,
                "error": f"all backends failed: bnb={bnb_error}, mlx={str(mlx_exc)[:100]}, gguf={str(gguf_exc)[:100]}",
            }
            json.dump(result, sys.stdout)
            sys.exit(0)

load_latency_s = time.monotonic() - start_load
rss_after_load = proc.memory_info().rss

# Warmup inference: one small RAG faithfulness prompt from the Lynx model card
prompt = (
    "You are a RAG evaluator. Given the context and the answer, determine faithfulness.\\n"
    "Context: Apple was founded in 1976.\\n"
    "Question: When was Apple founded?\\n"
    "Answer: Apple was founded in 1976 by Steve Jobs.\\n"
    "Is the answer faithful to the context? Answer YES or NO and explain briefly."
)

start_inf = time.monotonic()
try:
    if backend_used == "mlx-lm":
        import mlx_lm
        output = mlx_lm.generate(model, tokenizer, prompt=prompt, max_tokens=50, verbose=False)
        generated = str(output)
    elif backend_used == "llama-cpp-gguf":
        output = model(prompt, max_tokens=50, stop=["\\n\\n"])
        generated = output["choices"][0]["text"]
    else:
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with __import__("torch").no_grad():
            out = model.generate(**inputs, max_new_tokens=50)
        generated = tokenizer.decode(out[0], skip_special_tokens=True)[:200]
except Exception as inf_exc:
    generated = f"error: {inf_exc}"
inf_latency_s = time.monotonic() - start_inf

warmup_rss = proc.memory_info().rss

result = {
    "model": "Patronus-Lynx-8B",
    "hub_id": model_name,
    "backend": backend_used,
    "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
    "rss_after_load_mb": round(rss_after_load / 1024**2, 1),
    "rss_after_warmup_mb": round(warmup_rss / 1024**2, 1),
    "load_latency_s": round(load_latency_s, 2),
    "inf_latency_s": round(inf_latency_s, 4),
    "warmup_output_snippet": (generated[:80] if generated else None),
    "error": None,
}
json.dump(result, sys.stdout)
"""

_PROMETHEUS_WORKER = """
import json, sys, time, os
import psutil

proc = psutil.Process(os.getpid())
baseline_rss = proc.memory_info().rss

start_load = time.monotonic()

model_name = "prometheus-eval/prometheus-7b-v2.0"
backend_used = None
model = None
tokenizer = None

# Try bitsandbytes 4-bit first
try:
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    import torch

    bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name, quantization_config=bnb_config, device_map="auto"
    )
    backend_used = "bitsandbytes-4bit"
except Exception as bnb_exc:
    bnb_error = str(bnb_exc)[:200]
    try:
        import mlx_lm
        model, tokenizer = mlx_lm.load(model_name)
        backend_used = "mlx-lm"
    except Exception as mlx_exc:
        result = {
            "model": "Prometheus-2-7B",
            "hub_id": model_name,
            "backend": None,
            "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
            "rss_after_load_mb": None,
            "rss_after_warmup_mb": None,
            "load_latency_s": None,
            "inf_latency_s": None,
            "warmup_score": None,
            "error": f"all backends failed: bnb={bnb_error}, mlx={str(mlx_exc)[:100]}",
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

load_latency_s = time.monotonic() - start_load
rss_after_load = proc.memory_info().rss

# Warmup inference: one absolute-grading prompt with a stub rubric from the Prometheus model card
prompt = (
    "###Task Description:\\n"
    "An instruction, a response to evaluate, a reference answer, and a score rubric are given.\\n"
    "###Instruction:\\nWhat is the capital of France?\\n"
    "###Response to evaluate:\\nThe capital of France is Paris.\\n"
    "###Reference Answer (Score 5):\\nThe capital of France is Paris.\\n"
    "###Score Rubric:\\n"
    "[Is the response factually correct?]\\n"
    "Score 1: Completely incorrect.\\nScore 5: Fully correct.\\n"
    "###Feedback: "
)

start_inf = time.monotonic()
try:
    if backend_used == "mlx-lm":
        import mlx_lm
        output = mlx_lm.generate(model, tokenizer, prompt=prompt, max_tokens=50, verbose=False)
        generated = str(output)
    else:
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with __import__("torch").no_grad():
            out = model.generate(**inputs, max_new_tokens=50)
        generated = tokenizer.decode(out[0], skip_special_tokens=True)[:200]
except Exception as inf_exc:
    generated = f"error: {inf_exc}"
inf_latency_s = time.monotonic() - start_inf

warmup_rss = proc.memory_info().rss

result = {
    "model": "Prometheus-2-7B",
    "hub_id": model_name,
    "backend": backend_used,
    "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
    "rss_after_load_mb": round(rss_after_load / 1024**2, 1),
    "rss_after_warmup_mb": round(warmup_rss / 1024**2, 1),
    "load_latency_s": round(load_latency_s, 2),
    "inf_latency_s": round(inf_latency_s, 4),
    "warmup_output_snippet": (generated[:80] if generated else None),
    "error": None,
}
json.dump(result, sys.stdout)
"""


# ---------------------------------------------------------------------------
# System baseline
# ---------------------------------------------------------------------------


def _system_memory_baseline() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "total_mb": round(vm.total / 1024**2, 1),
        "available_mb": round(vm.available / 1024**2, 1),
        "used_mb": round(vm.used / 1024**2, 1),
        "percent": vm.percent,
    }


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


def _run_model_worker(worker_script: str, python: str) -> dict[str, Any]:
    """Run a worker script in an isolated subprocess. Returns parsed JSON result."""
    env = {**os.environ}
    # Disable tokenizers parallelism warning
    env["TOKENIZERS_PARALLELISM"] = "false"
    # Redirect HuggingFace progress bars to stderr only
    env["HF_DATASETS_DISABLE_PROGRESS_BARS"] = "1"

    result = subprocess.run(
        [python, "-c", worker_script],
        capture_output=False,
        stdout=subprocess.PIPE,
        stderr=None,  # inherit stderr so download progress is visible
        env=env,
        timeout=3600,  # 1-hour cap; model downloads can be slow
    )

    if result.returncode != 0 and not result.stdout:
        return {
            "model": "unknown",
            "error": f"subprocess exit {result.returncode} with no stdout",
            "backend": None,
        }

    try:
        return json.loads(result.stdout.decode())
    except json.JSONDecodeError as exc:
        return {
            "model": "unknown",
            "error": f"JSON parse failed: {exc}; stdout={result.stdout[:200]!r}",
            "backend": None,
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    python = sys.executable

    print("=== FinSentry Frontier Model Memory Measurement ===", file=sys.stderr)
    print("", file=sys.stderr)

    mem_before = _system_memory_baseline()
    print(
        f"System memory before run: "
        f"{mem_before['available_mb']:.0f} MB available / {mem_before['total_mb']:.0f} MB total "
        f"({mem_before['percent']}% used)",
        file=sys.stderr,
    )
    print("", file=sys.stderr)

    models = [
        ("HHEM-2.1-Open", _HHEM_WORKER),
        ("Patronus-Lynx-8B", _LYNX_WORKER),
        ("Prometheus-2-7B", _PROMETHEUS_WORKER),
    ]

    results: list[dict[str, Any]] = []

    for name, worker in models:
        print(f"--- Measuring {name} ---", file=sys.stderr)
        available_mb = psutil.virtual_memory().available / 1024**2
        if available_mb < 1000:
            msg = (
                f"STOPPED before {name}: only {available_mb:.0f} MB available, "
                "likely to exhaust memory. Previous model may not have been released."
            )
            print(msg, file=sys.stderr)
            results.append({"model": name, "error": msg, "backend": None})
            break

        t0 = time.monotonic()
        result = _run_model_worker(worker, python)
        wall_s = time.monotonic() - t0

        result["total_wall_s"] = round(wall_s, 1)
        results.append(result)

        if result.get("error"):
            print(f"  ERROR: {result['error']}", file=sys.stderr)
        else:
            print(
                f"  baseline_rss={result.get('baseline_rss_mb')} MB  "
                f"after_load={result.get('rss_after_load_mb')} MB  "
                f"after_warmup={result.get('rss_after_warmup_mb')} MB  "
                f"load={result.get('load_latency_s')}s  "
                f"inf={result.get('inf_latency_s')}s  "
                f"backend={result.get('backend')}",
                file=sys.stderr,
            )
        print("", file=sys.stderr)

    mem_after = _system_memory_baseline()

    output = {
        "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system_memory_before": mem_before,
        "system_memory_after": mem_after,
        "models": results,
    }

    # Summary table to stderr
    print("=== Summary ===", file=sys.stderr)
    print(
        f"{'Model':<22} {'backend':<20} {'baseline':>10} {'load':>10} {'warmup':>10} "
        f"{'load_s':>8} {'inf_s':>8} {'error':<40}",
        file=sys.stderr,
    )
    print("-" * 120, file=sys.stderr)
    for r in results:
        print(
            f"{r.get('model','?'):<22} "
            f"{str(r.get('backend','?')):<20} "
            f"{str(r.get('baseline_rss_mb','?'))+' MB':>10} "
            f"{str(r.get('rss_after_load_mb','?'))+' MB':>10} "
            f"{str(r.get('rss_after_warmup_mb','?'))+' MB':>10} "
            f"{str(r.get('load_latency_s','?')):>8} "
            f"{str(r.get('inf_latency_s','?')):>8} "
            f"{str(r.get('error',''))[:40]:<40}",
            file=sys.stderr,
        )

    # JSON to stdout
    json.dump(output, sys.stdout, indent=2)
    print("", file=sys.stdout)  # trailing newline


if __name__ == "__main__":
    main()
