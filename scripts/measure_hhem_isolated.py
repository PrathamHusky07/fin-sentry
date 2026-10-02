#!/usr/bin/env python3
"""Run HHEM-2.1-Open measurement in the isolated .venv-hhem/ virtualenv.

The main project venv uses transformers 5.x, which is incompatible with HHEM's
transformers 4.x API. This script shells to .venv-hhem/bin/python (which pins
transformers>=4.40,<5.0) to load HHEM in isolation.

Usage:
    .venv/bin/python scripts/measure_hhem_isolated.py

Output:
    docs/measurements/hhem-isolated-day5a-m0.json

If HHEM fails to load, the JSON will have error != null and all model metrics
will be null. Phase 0B Task 1A terminates on any non-null error.

vm_stat notes:
  - Swapouts is a monotonic cumulative counter since boot, not a current memory snapshot.
  - sampled_peak_rss_mb is sampled at ~100ms cadence; spikes shorter than 100ms can be missed.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any


_HHEM_VENV_PYTHON = pathlib.Path(__file__).parent.parent / ".venv-hhem" / "bin" / "python"
_OUTPUT_PATH = pathlib.Path(__file__).parent.parent / "docs" / "measurements" / "hhem-isolated-day5a-m0.json"

# Same worker code as _HHEM_WORKER in measure_frontier_models.py.
# Keep in sync if the worker logic changes.
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

# MPS baseline before any model load
mps_alloc_baseline = None
mps_driver_baseline = None
if _mps_available:
    try:
        mps_alloc_baseline = round(torch.mps.current_allocated_memory() / 1024**2, 1)
        mps_driver_baseline = round(torch.mps.driver_allocated_memory() / 1024**2, 1)
    except Exception:
        pass

model_name = "vectara/hallucination_evaluation_model"

try:
    start_load = time.monotonic()
    # Phase 0B tried: tokenizer = DebertaV2Tokenizer.from_pretrained(model_name)
    # That failed because the HHEM repo snapshot has no tokenizer vocab assets
    # (verified in Task 1A). HHEM is built on microsoft/deberta-v3-base, so load
    # the tokenizer from the base model. The HHEM model weights are still loaded
    # from vectara/hallucination_evaluation_model with trust_remote_code=True.
    from transformers import DebertaV2Tokenizer, AutoModelForSequenceClassification
    import torch

    tokenizer = DebertaV2Tokenizer.from_pretrained("microsoft/deberta-v3-base")
    model = AutoModelForSequenceClassification.from_pretrained(model_name, trust_remote_code=True)
    model.eval()

    load_latency_s = time.monotonic() - start_load
    rss_after_load = proc.memory_info().rss

    # Inspect actual device placement (distinct from requested backend)
    try:
        first_param_device = str(next(model.parameters()).device)
    except StopIteration:
        first_param_device = "unknown"
    hf_device_map = getattr(model, "hf_device_map", None)
    if first_param_device.startswith("mps"):
        actual_device = "mps"
    elif first_param_device.startswith("cuda"):
        actual_device = "cuda"
    elif first_param_device.startswith("cpu"):
        actual_device = "cpu"
    else:
        actual_device = first_param_device
    layers_on_cpu = None
    layers_on_mps = None
    if hf_device_map:
        layers_on_cpu = sum(1 for v in hf_device_map.values() if str(v) == "cpu")
        layers_on_mps = sum(1 for v in hf_device_map.values() if str(v).startswith("mps"))

    _mps_alloc_after_load = None
    _mps_driver_after_load = None
    if _mps_available:
        try:
            _mps_alloc_after_load = round(torch.mps.current_allocated_memory() / 1024**2, 1)
            _mps_driver_after_load = round(torch.mps.driver_allocated_memory() / 1024**2, 1)
        except Exception:
            pass

    # Warmup with a single consistent pair
    warmup_pairs = [["The capital of France is Paris.", "France's capital is Paris."]]
    start_inf = time.monotonic()
    with torch.no_grad():
        inputs = tokenizer.batch_encode_plus(warmup_pairs, return_tensors="pt", truncation=True, max_length=512)
        logits = model(**inputs).logits.squeeze(dim=1)
        warmup_score = torch.sigmoid(logits).item()
    inf_latency_s = time.monotonic() - start_inf

    # Three-pair sanity set: consistent / contradictory / unrelated
    sanity_pairs = [
        ["The capital of France is Paris. It has been the capital since the 10th century.", "Paris is the capital of France."],
        ["The capital of France is Paris.", "The capital of France is Berlin."],
        ["The capital of France is Paris.", "The company released a new laptop in June."],
    ]
    sanity_labels = ["consistent", "contradictory", "unrelated"]
    sanity_scores = {}
    with torch.no_grad():
        for label, pair in zip(sanity_labels, sanity_pairs):
            inp = tokenizer.batch_encode_plus([pair], return_tensors="pt", truncation=True, max_length=512)
            lg = model(**inp).logits.squeeze(dim=1)
            sanity_scores[label] = round(torch.sigmoid(lg).item(), 4)

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
        "requested_backend": "transformers-deberta-v2",
        "actual_device": actual_device,
        "hf_device_map": hf_device_map,
        "layers_on_cpu": layers_on_cpu,
        "layers_on_mps": layers_on_mps,
        "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
        "rss_after_load_mb": round(rss_after_load / 1024**2, 1),
        "rss_after_warmup_mb": round(warmup_rss / 1024**2, 1),
        "sampled_peak_rss_mb": round(peak_rss / 1024**2, 1),
        "mps_allocated_mb_baseline": mps_alloc_baseline,
        "mps_driver_allocated_mb_baseline": mps_driver_baseline,
        "mps_allocated_mb_after_load": _mps_alloc_after_load,
        "mps_driver_allocated_mb_after_load": _mps_driver_after_load,
        "mps_allocated_mb_after_warmup": _mps_alloc_after_warmup,
        "mps_driver_allocated_mb_after_warmup": _mps_driver_after_warmup,
        "load_latency_s": round(load_latency_s, 2),
        "inf_latency_s": round(inf_latency_s, 4),
        "warmup_score": round(warmup_score, 4),
        "sanity_scores": sanity_scores,
        "error": None,
    }
except Exception as exc:
    _stop_sampler.set()
    _sampler_thread.join(timeout=1.0)
    peak_rss = _peak_rss[0]
    result = {
        "model": "HHEM-2.1-Open",
        "hub_id": model_name,
        "requested_backend": "transformers-deberta-v2",
        "actual_device": None,
        "hf_device_map": None,
        "layers_on_cpu": None,
        "layers_on_mps": None,
        "baseline_rss_mb": round(baseline_rss / 1024**2, 1),
        "rss_after_load_mb": None,
        "rss_after_warmup_mb": None,
        "sampled_peak_rss_mb": round(peak_rss / 1024**2, 1),
        "mps_allocated_mb_baseline": mps_alloc_baseline,
        "mps_driver_allocated_mb_baseline": mps_driver_baseline,
        "mps_allocated_mb_after_load": None,
        "mps_driver_allocated_mb_after_load": None,
        "mps_allocated_mb_after_warmup": None,
        "mps_driver_allocated_mb_after_warmup": None,
        "load_latency_s": None,
        "inf_latency_s": None,
        "warmup_score": None,
        "sanity_scores": None,
        "error": str(exc),
    }

json.dump(result, sys.stdout)
"""


def _capture_vm_stat(label: str) -> dict[str, Any]:
    """Run /usr/bin/vm_stat and parse key page counts. macOS only.

    Swapouts is a monotonic cumulative counter since boot, not a current memory snapshot.
    Page fields (pages_free, pages_active, etc.) reflect current kernel page accounting.
    """
    vm_stat_path = "/usr/bin/vm_stat"
    if not os.path.exists(vm_stat_path):
        return {
            "label": label,
            "error": "vm_stat not available",
            "raw": None,
            "parsed_pages": None,
            "parsed_mb": None,
            "parsed_counters": None,
        }
    try:
        r = subprocess.run([vm_stat_path], capture_output=True, text=True, timeout=5)
        raw = r.stdout
    except Exception as exc:
        return {
            "label": label,
            "error": str(exc),
            "raw": None,
            "parsed_pages": None,
            "parsed_mb": None,
            "parsed_counters": None,
        }

    page_size = 16384
    for line in raw.splitlines():
        if "page size of" in line:
            try:
                page_size = int(line.split("page size of")[1].split("bytes")[0].strip())
            except (ValueError, IndexError):
                pass

    # Only page-count fields get MB conversion; swapouts is a cumulative counter.
    page_fields = [
        ("Pages free:", "pages_free"),
        ("Pages active:", "pages_active"),
        ("Pages inactive:", "pages_inactive"),
        ("Pages wired down:", "pages_wired_down"),
        ("Pages occupied by compressor:", "pages_occupied_by_compressor"),
    ]
    counter_fields = [
        ("Swapouts:", "swapouts"),
    ]

    parsed_pages: dict[str, int] = {}
    parsed_counters: dict[str, int] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        for key, field in page_fields:
            if stripped.startswith(key):
                try:
                    val = int(stripped.split(":")[1].strip().rstrip("."))
                    parsed_pages[field] = val
                except (ValueError, IndexError):
                    pass
        for key, field in counter_fields:
            if stripped.startswith(key):
                try:
                    val = int(stripped.split(":")[1].strip().rstrip("."))
                    parsed_counters[field] = val
                except (ValueError, IndexError):
                    pass

    parsed_mb: dict[str, float] = {k: round(v * page_size / 1024**2, 1) for k, v in parsed_pages.items()}

    return {
        "label": label,
        "page_size_bytes": page_size,
        "raw": raw,
        "parsed_pages": parsed_pages,
        "parsed_mb": parsed_mb,
        "parsed_counters": parsed_counters,
    }


def main() -> None:
    venv_python = str(_HHEM_VENV_PYTHON)
    if not pathlib.Path(venv_python).exists():
        print(f"ERROR: {venv_python} not found. Create the venv first:", file=sys.stderr)
        print("  python3 -m venv .venv-hhem", file=sys.stderr)
        print("  .venv-hhem/bin/pip install 'transformers>=4.40,<5.0' torch>=2.1 sentencepiece>=0.2 protobuf psutil huggingface-hub", file=sys.stderr)
        sys.exit(1)

    print("=== HHEM Isolated Measurement (.venv-hhem) ===", file=sys.stderr)
    print(f"Python: {venv_python}", file=sys.stderr)

    vm_before = _capture_vm_stat("before_hhem_isolated")

    env = {**os.environ, "TOKENIZERS_PARALLELISM": "false", "HF_DATASETS_DISABLE_PROGRESS_BARS": "1"}

    t0 = time.monotonic()
    proc = subprocess.run(
        [venv_python, "-c", _HHEM_WORKER],
        stdout=subprocess.PIPE,
        stderr=None,  # inherit so model download progress is visible
        env=env,
        timeout=3600,
    )
    wall_s = time.monotonic() - t0

    vm_after = _capture_vm_stat("after_hhem_isolated")

    if proc.returncode != 0 and not proc.stdout:
        model_result: dict[str, Any] = {
            "model": "HHEM-2.1-Open",
            "error": f"subprocess exit {proc.returncode} with no stdout",
            "requested_backend": "transformers-deberta-v2",
        }
    else:
        try:
            model_result = json.loads(proc.stdout.decode())
        except json.JSONDecodeError as exc:
            model_result = {
                "model": "HHEM-2.1-Open",
                "error": f"JSON parse failed: {exc}; stdout={proc.stdout[:200]!r}",
                "requested_backend": "transformers-deberta-v2",
            }

    model_result["total_wall_s"] = round(wall_s, 1)

    output = {
        "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "venv": ".venv-hhem",
        "vm_stat_snapshots": [vm_before, vm_after],
        "model": model_result,
    }

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")

    error = model_result.get("error")
    if error:
        print(f"\nHHEM FAILED: {error}", file=sys.stderr)
        print(f"Output written to {_OUTPUT_PATH}", file=sys.stderr)
        sys.exit(1)
    else:
        sanity = model_result.get("sanity_scores") or {}
        print("\nHHEM SUCCESS:", file=sys.stderr)
        print(f"  sampled_peak_rss_mb={model_result.get('sampled_peak_rss_mb')}", file=sys.stderr)
        print(f"  actual_device={model_result.get('actual_device')}", file=sys.stderr)
        print(f"  mps_allocated_mb_baseline={model_result.get('mps_allocated_mb_baseline')}", file=sys.stderr)
        print(f"  mps_allocated_mb_after_load={model_result.get('mps_allocated_mb_after_load')}", file=sys.stderr)
        print(f"  mps_allocated_mb_after_warmup={model_result.get('mps_allocated_mb_after_warmup')}", file=sys.stderr)
        print(f"  warmup_score={model_result.get('warmup_score')}", file=sys.stderr)
        print(f"  sanity consistent={sanity.get('consistent')}  contradictory={sanity.get('contradictory')}  unrelated={sanity.get('unrelated')}", file=sys.stderr)
        print(f"  load_latency_s={model_result.get('load_latency_s')}", file=sys.stderr)
        print(f"  inf_latency_s={model_result.get('inf_latency_s')}", file=sys.stderr)
        print(f"Output written to {_OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
