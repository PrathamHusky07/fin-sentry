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
# vm_stat capture (macOS only; no-ops on other platforms)
# ---------------------------------------------------------------------------

def _capture_vm_stat(label: str) -> dict[str, Any]:
    """Run /usr/bin/vm_stat and parse key page counts. macOS only."""
    vm_stat_path = "/usr/bin/vm_stat"
    if not os.path.exists(vm_stat_path):
        return {"label": label, "error": "vm_stat not available", "raw": None, "parsed_pages": None, "parsed_mb": None}
    try:
        result = subprocess.run(
            [vm_stat_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        raw = result.stdout
    except Exception as exc:
        return {"label": label, "error": str(exc), "raw": None, "parsed_pages": None, "parsed_mb": None}

    # Default Apple Silicon page size; overridden from header if present
    page_size = 16384
    for line in raw.splitlines():
        if "page size of" in line:
            try:
                page_size = int(line.split("page size of")[1].split("bytes")[0].strip())
            except (ValueError, IndexError):
                pass

    fields_to_extract = [
        ("Pages free:", "pages_free"),
        ("Pages active:", "pages_active"),
        ("Pages inactive:", "pages_inactive"),
        ("Pages wired down:", "pages_wired_down"),
        ("Pages occupied by compressor:", "pages_occupied_by_compressor"),
        ("Swapouts:", "swapouts"),
    ]
    parsed: dict[str, int] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        for key, field in fields_to_extract:
            if stripped.startswith(key):
                try:
                    val = int(stripped.split(":")[1].strip().rstrip("."))
                    parsed[field] = val
                except (ValueError, IndexError):
                    pass

    parsed_mb: dict[str, float] = {k: round(v * page_size / 1024**2, 1) for k, v in parsed.items()}

    return {
        "label": label,
        "page_size_bytes": page_size,
        "raw": raw,
        "parsed_pages": parsed,
        "parsed_mb": parsed_mb,
    }


# ---------------------------------------------------------------------------
# Per-model subprocess worker scripts
# These run inside isolated python processes so RSS is measured cleanly.
# Each worker emits a single JSON object to stdout.
# New fields vs. original: peak_rss_mb, mps_allocated_mb_after_load,
#   mps_allocated_mb_after_warmup, mps_driver_allocated_mb_after_warmup.
# ---------------------------------------------------------------------------

_HHEM_WORKER = """
import json, sys, time, os, threading
import psutil

proc = psutil.Process(os.getpid())
baseline_rss = proc.memory_info().rss

_peak_rss = [baseline_rss]
_stop_sampler = threading.Event()

def _rss_sampler():
    while not _stop_sampler.is_set():
        try:
            rss = proc.memory_info().rss
            if rss > _peak_rss[0]:
                _peak_rss[0] = rss
        except Exception:
            pass
        _stop_sampler.wait(0.1)

_sampler_thread = threading.Thread(target=_rss_sampler, daemon=True)
_sampler_thread.start()

_mps_available = False
try:
    import torch
    if torch.backends.mps.is_available():
        _mps_available = True
except Exception:
    pass

model_name = "vectara/hallucination_evaluation_model"

try:
    start_load = time.monotonic()
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch

    # use_fast=False: HHEM uses DeBERTa-v3 tokenizer which needs the slow SentencePiece path
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True, use_fast=False)
    model = AutoModelForSequenceClassification.from_pretrained(model_name, trust_remote_code=True)
    model.eval()

    load_latency_s = time.monotonic() - start_load
    rss_after_load = proc.memory_info().rss

    _mps_alloc_after_load = None
    _mps_driver_after_load = None
    if _mps_available:
        try:
            _mps_alloc_after_load = round(torch.mps.current_allocated_memory() / 1024**2, 1)
            _mps_driver_after_load = round(torch.mps.driver_allocated_memory() / 1024**2, 1)
        except Exception:
            pass

    pairs = [["The capital of France is Paris.", "France's capital is Paris."]]
    start_inf = time.monotonic()
    with torch.no_grad():
        inputs = tokenizer.batch_encode_plus(pairs, return_tensors="pt", truncation=True, max_length=512)
        logits = model(**inputs).logits.squeeze(dim=1)
        score = torch.sigmoid(logits).item()
    inf_latency_s = time.monotonic() - start_inf

    warmup_rss = proc.memory_info().rss
    _stop_sampler.set()
    _sampler_thread.join(timeout=1.0)
    peak_rss = _peak_rss[0]

    _mps_alloc_after_warmup = None
    _mps_driver_after_warmup = None
    if _mps_available:
        try:
            _mps_alloc_after_warmup = round(torch.mps.current_allocated_memory() / 1024**2, 1)
            _mps_driver_after_warmup = round(torch.mps.driver_allocated_memory() / 1024**2, 1)
        except Exception:
            pass

    result = {
        "model": "HHEM-2.1-Open",
        "hub_id": model_name,
        "backend": "transformers",
        "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
        "rss_after_load_mb": round(rss_after_load / 1024**2, 1),
        "rss_after_warmup_mb": round(warmup_rss / 1024**2, 1),
        "peak_rss_mb": round(peak_rss / 1024**2, 1),
        "mps_allocated_mb_after_load": _mps_alloc_after_load,
        "mps_allocated_mb_after_warmup": _mps_alloc_after_warmup,
        "mps_driver_allocated_mb_after_warmup": _mps_driver_after_warmup,
        "load_latency_s": round(load_latency_s, 2),
        "inf_latency_s": round(inf_latency_s, 4),
        "warmup_score": round(score, 4),
        "error": None,
    }
except Exception as exc:
    _stop_sampler.set()
    _sampler_thread.join(timeout=1.0)
    peak_rss = _peak_rss[0]
    result = {
        "model": "HHEM-2.1-Open",
        "hub_id": model_name,
        "backend": None,
        "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
        "rss_after_load_mb": None,
        "rss_after_warmup_mb": None,
        "peak_rss_mb": round(peak_rss / 1024**2, 1),
        "mps_allocated_mb_after_load": None,
        "mps_allocated_mb_after_warmup": None,
        "mps_driver_allocated_mb_after_warmup": None,
        "load_latency_s": None,
        "inf_latency_s": None,
        "warmup_score": None,
        "error": str(exc),
    }

json.dump(result, sys.stdout)
"""

_LYNX_WORKER = """
import json, sys, time, os, threading
import psutil

proc = psutil.Process(os.getpid())
baseline_rss = proc.memory_info().rss

_peak_rss = [baseline_rss]
_stop_sampler = threading.Event()

def _rss_sampler():
    while not _stop_sampler.is_set():
        try:
            rss = proc.memory_info().rss
            if rss > _peak_rss[0]:
                _peak_rss[0] = rss
        except Exception:
            pass
        _stop_sampler.wait(0.1)

_sampler_thread = threading.Thread(target=_rss_sampler, daemon=True)
_sampler_thread.start()

_mps_available = False
try:
    import torch
    if torch.backends.mps.is_available():
        _mps_available = True
except Exception:
    pass

start_load = time.monotonic()

model_name = "PatronusAI/Llama-3-Patronus-Lynx-8B-Instruct"
backend_used = None
model = None
tokenizer = None

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
        try:
            from llama_cpp import Llama
            from huggingface_hub import hf_hub_download
            gguf_repo = "PatronusAI/Patronus-Lynx-8B-Instruct-Q4_K_M-GGUF"
            gguf_path = hf_hub_download(repo_id=gguf_repo, filename="Patronus-Lynx-8B-Instruct-Q4_K_M.gguf")
            model = Llama(model_path=gguf_path, n_ctx=2048, verbose=False)
            tokenizer = None
            backend_used = "llama-cpp-gguf"
        except Exception as gguf_exc:
            _stop_sampler.set()
            _sampler_thread.join(timeout=1.0)
            peak_rss = _peak_rss[0]
            result = {
                "model": "Patronus-Lynx-8B",
                "hub_id": model_name,
                "backend": None,
                "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
                "rss_after_load_mb": None,
                "rss_after_warmup_mb": None,
                "peak_rss_mb": round(peak_rss / 1024**2, 1),
                "mps_allocated_mb_after_load": None,
                "mps_allocated_mb_after_warmup": None,
                "mps_driver_allocated_mb_after_warmup": None,
                "load_latency_s": None,
                "inf_latency_s": None,
                "warmup_score": None,
                "error": f"all backends failed: bnb={bnb_error}, mlx={str(mlx_exc)[:100]}, gguf={str(gguf_exc)[:100]}",
            }
            json.dump(result, sys.stdout)
            sys.exit(0)

load_latency_s = time.monotonic() - start_load
rss_after_load = proc.memory_info().rss

_mps_alloc_after_load = None
_mps_driver_after_load = None
if _mps_available:
    try:
        import torch
        _mps_alloc_after_load = round(torch.mps.current_allocated_memory() / 1024**2, 1)
        _mps_driver_after_load = round(torch.mps.driver_allocated_memory() / 1024**2, 1)
    except Exception:
        pass

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
        import torch
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=50)
        generated = tokenizer.decode(out[0], skip_special_tokens=True)[:200]
except Exception as inf_exc:
    generated = f"error: {inf_exc}"
inf_latency_s = time.monotonic() - start_inf

warmup_rss = proc.memory_info().rss
_stop_sampler.set()
_sampler_thread.join(timeout=1.0)
peak_rss = _peak_rss[0]

_mps_alloc_after_warmup = None
_mps_driver_after_warmup = None
if _mps_available:
    try:
        import torch
        _mps_alloc_after_warmup = round(torch.mps.current_allocated_memory() / 1024**2, 1)
        _mps_driver_after_warmup = round(torch.mps.driver_allocated_memory() / 1024**2, 1)
    except Exception:
        pass

result = {
    "model": "Patronus-Lynx-8B",
    "hub_id": model_name,
    "backend": backend_used,
    "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
    "rss_after_load_mb": round(rss_after_load / 1024**2, 1),
    "rss_after_warmup_mb": round(warmup_rss / 1024**2, 1),
    "peak_rss_mb": round(peak_rss / 1024**2, 1),
    "mps_allocated_mb_after_load": _mps_alloc_after_load,
    "mps_allocated_mb_after_warmup": _mps_alloc_after_warmup,
    "mps_driver_allocated_mb_after_warmup": _mps_driver_after_warmup,
    "load_latency_s": round(load_latency_s, 2),
    "inf_latency_s": round(inf_latency_s, 4),
    "warmup_output_snippet": (generated[:80] if generated else None),
    "error": None,
}
json.dump(result, sys.stdout)
"""

_PROMETHEUS_WORKER = """
import json, sys, time, os, threading
import psutil

proc = psutil.Process(os.getpid())
baseline_rss = proc.memory_info().rss

_peak_rss = [baseline_rss]
_stop_sampler = threading.Event()

def _rss_sampler():
    while not _stop_sampler.is_set():
        try:
            rss = proc.memory_info().rss
            if rss > _peak_rss[0]:
                _peak_rss[0] = rss
        except Exception:
            pass
        _stop_sampler.wait(0.1)

_sampler_thread = threading.Thread(target=_rss_sampler, daemon=True)
_sampler_thread.start()

_mps_available = False
try:
    import torch
    if torch.backends.mps.is_available():
        _mps_available = True
except Exception:
    pass

start_load = time.monotonic()

model_name = "prometheus-eval/prometheus-7b-v2.0"
backend_used = None
model = None
tokenizer = None

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
        _stop_sampler.set()
        _sampler_thread.join(timeout=1.0)
        peak_rss = _peak_rss[0]
        result = {
            "model": "Prometheus-2-7B",
            "hub_id": model_name,
            "backend": None,
            "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
            "rss_after_load_mb": None,
            "rss_after_warmup_mb": None,
            "peak_rss_mb": round(peak_rss / 1024**2, 1),
            "mps_allocated_mb_after_load": None,
            "mps_allocated_mb_after_warmup": None,
            "mps_driver_allocated_mb_after_warmup": None,
            "load_latency_s": None,
            "inf_latency_s": None,
            "warmup_score": None,
            "error": f"all backends failed: bnb={bnb_error}, mlx={str(mlx_exc)[:100]}",
        }
        json.dump(result, sys.stdout)
        sys.exit(0)

load_latency_s = time.monotonic() - start_load
rss_after_load = proc.memory_info().rss

_mps_alloc_after_load = None
_mps_driver_after_load = None
if _mps_available:
    try:
        import torch
        _mps_alloc_after_load = round(torch.mps.current_allocated_memory() / 1024**2, 1)
        _mps_driver_after_load = round(torch.mps.driver_allocated_memory() / 1024**2, 1)
    except Exception:
        pass

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
        import torch
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=50)
        generated = tokenizer.decode(out[0], skip_special_tokens=True)[:200]
except Exception as inf_exc:
    generated = f"error: {inf_exc}"
inf_latency_s = time.monotonic() - start_inf

warmup_rss = proc.memory_info().rss
_stop_sampler.set()
_sampler_thread.join(timeout=1.0)
peak_rss = _peak_rss[0]

_mps_alloc_after_warmup = None
_mps_driver_after_warmup = None
if _mps_available:
    try:
        import torch
        _mps_alloc_after_warmup = round(torch.mps.current_allocated_memory() / 1024**2, 1)
        _mps_driver_after_warmup = round(torch.mps.driver_allocated_memory() / 1024**2, 1)
    except Exception:
        pass

result = {
    "model": "Prometheus-2-7B",
    "hub_id": model_name,
    "backend": backend_used,
    "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
    "rss_after_load_mb": round(rss_after_load / 1024**2, 1),
    "rss_after_warmup_mb": round(warmup_rss / 1024**2, 1),
    "peak_rss_mb": round(peak_rss / 1024**2, 1),
    "mps_allocated_mb_after_load": _mps_alloc_after_load,
    "mps_allocated_mb_after_warmup": _mps_alloc_after_warmup,
    "mps_driver_allocated_mb_after_warmup": _mps_driver_after_warmup,
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
    env["TOKENIZERS_PARALLELISM"] = "false"
    env["HF_DATASETS_DISABLE_PROGRESS_BARS"] = "1"

    result = subprocess.run(
        [python, "-c", worker_script],
        capture_output=False,
        stdout=subprocess.PIPE,
        stderr=None,  # inherit stderr so download progress is visible
        env=env,
        timeout=3600,
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

    vm_stat_snapshots: list[dict[str, Any]] = []

    models = [
        ("HHEM-2.1-Open", _HHEM_WORKER),
        ("Patronus-Lynx-8B", _LYNX_WORKER),
        ("Prometheus-2-7B", _PROMETHEUS_WORKER),
    ]

    results: list[dict[str, Any]] = []

    for idx, (name, worker) in enumerate(models):
        print(f"--- Measuring {name} ---", file=sys.stderr)

        if idx == 0:
            vm_stat_snapshots.append(_capture_vm_stat("before_first_model"))

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

        vm_stat_snapshots.append(_capture_vm_stat(f"after_{name.lower().replace('-', '_').replace('.', '_')}"))

        if result.get("error"):
            print(f"  ERROR: {result['error']}", file=sys.stderr)
        else:
            print(
                f"  baseline_rss={result.get('baseline_rss_mb')} MB  "
                f"after_load={result.get('rss_after_load_mb')} MB  "
                f"after_warmup={result.get('rss_after_warmup_mb')} MB  "
                f"peak_rss={result.get('peak_rss_mb')} MB  "
                f"mps_load={result.get('mps_allocated_mb_after_load')} MB  "
                f"mps_warmup={result.get('mps_allocated_mb_after_warmup')} MB  "
                f"load={result.get('load_latency_s')}s  "
                f"inf={result.get('inf_latency_s')}s  "
                f"backend={result.get('backend')}",
                file=sys.stderr,
            )
        print("", file=sys.stderr)

    vm_stat_snapshots.append(_capture_vm_stat("after_all_models"))

    mem_after = _system_memory_baseline()

    output = {
        "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": "Apple Silicon, 24 GB unified memory",
        "python_version": "3.13",
        "transformers_version": None,  # filled per-model; varies by venv
        "system_memory_before": mem_before,
        "system_memory_after": mem_after,
        "rss_note": (
            "psutil.memory_info().rss measures CPU-side process RSS only. "
            "On Apple Silicon (unified memory), model weights are allocated via Metal/MPS "
            "and not reflected in psutil RSS. peak_rss_mb is the maximum RSS sampled at 100ms "
            "intervals during load + warmup. MPS fields (mps_allocated_mb_*) reflect GPU-resident "
            "weight bytes via torch.mps.current_allocated_memory() and are the correct capacity "
            "planning signal on this machine."
        ),
        "vm_stat_snapshots": vm_stat_snapshots,
        "models": results,
    }

    # Summary table to stderr
    print("=== Summary ===", file=sys.stderr)
    print(
        f"{'Model':<22} {'backend':<20} {'baseline':>10} {'peak_rss':>10} {'mps_load':>10} "
        f"{'load_s':>8} {'inf_s':>8} {'error':<40}",
        file=sys.stderr,
    )
    print("-" * 130, file=sys.stderr)
    for r in results:
        print(
            f"{r.get('model','?'):<22} "
            f"{str(r.get('backend','?')):<20} "
            f"{str(r.get('baseline_rss_mb','?'))+' MB':>10} "
            f"{str(r.get('peak_rss_mb','?'))+' MB':>10} "
            f"{str(r.get('mps_allocated_mb_after_load','?'))+' MB':>10} "
            f"{str(r.get('load_latency_s','?')):>8} "
            f"{str(r.get('inf_latency_s','?')):>8} "
            f"{str(r.get('error',''))[:40]:<40}",
            file=sys.stderr,
        )

    json.dump(output, sys.stdout, indent=2)
    print("", file=sys.stdout)


if __name__ == "__main__":
    main()
