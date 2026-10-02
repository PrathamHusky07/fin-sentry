#!/usr/bin/env python3
"""Measure simultaneous memory residency of Patronus Lynx 8B and Prometheus 2 7B.

Protocol:
  1. vm_stat baseline + MPS alloc baseline (parent process)
  2. Spawn subprocess A (Lynx). Wait for "READY" on stdout.
  3. vm_stat "one model resident" + A RSS.
  4. Spawn subprocess B (Prometheus). Wait for "READY" on stdout.
  5. vm_stat "two models resident" + A and B RSS.
  6. Send {cmd:infer} to A; wait for {result:DONE}.
  7. Send {cmd:infer} to B; wait for {result:DONE}.
     [7.5 stretch: load HHEM as subprocess C via .venv-hhem if Task 1 succeeded]
  8. Send {cmd:shutdown} to both; wait for clean exit.
  9. vm_stat "after_shutdown".

Hard gates (must all pass for DEMONSTRATED result):
  - Both reach READY
  - Neither killed by signal (exit code != 137)
  - Both inferences return DONE

Supporting diagnostics (reported but not gated):
  - pages_free trajectory
  - pages_occupied_by_compressor trajectory
  - swapouts delta (step 1 to step 9)
  - second-inference latency vs first

Usage:
    .venv/bin/python scripts/measure_frontier_residency.py [--skip-hhem-stretch]

Output:
    docs/measurements/frontier-residency-day5a-m0.json

vm_stat notes:
  - Swapouts is a monotonic cumulative counter since boot.
  - Low or zero pages_free is NOT a failure signal on Apple Silicon (macOS drives
    free pages toward zero while using compression and inactive-page reclamation).
  - sampled_peak_rss_mb is sampled at ~100ms cadence.
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import sys
import time
from typing import Any

import psutil


_OUTPUT_PATH = pathlib.Path(__file__).parent.parent / "docs" / "measurements" / "frontier-residency-day5a-m0.json"
_HHEM_VENV_PYTHON = pathlib.Path(__file__).parent.parent / ".venv-hhem" / "bin" / "python"


# ---------------------------------------------------------------------------
# Worker scripts (loaded as stdin-driven daemons after warmup)
# Each worker:
#   1. Loads model, runs warmup inference
#   2. Prints "READY" to stdout (JSON line: {"status":"READY","pid":N,...})
#   3. Enters stdin loop: {"cmd":"infer"} -> {"result":"DONE","latency_ms":N}
#                         {"cmd":"shutdown"} -> exits cleanly
# ---------------------------------------------------------------------------

_LYNX_RESIDENCY_WORKER = """
import json, sys, time, os
import psutil

proc = psutil.Process(os.getpid())
model_name = "PatronusAI/Llama-3-Patronus-Lynx-8B-Instruct"

_mps_available = False
actual_device = "unknown"
requested_backend = None

try:
    import torch
    if torch.backends.mps.is_available():
        _mps_available = True
except Exception:
    pass

model = None
tokenizer = None

try:
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    import torch
    bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name, quantization_config=bnb_config, device_map="auto")
    requested_backend = "bitsandbytes-4bit"
except Exception as bnb_exc:
    try:
        import mlx_lm
        model, tokenizer = mlx_lm.load(model_name)
        requested_backend = "mlx-lm"
    except Exception as mlx_exc:
        err = {"status": "ERROR", "pid": os.getpid(), "model": "Patronus-Lynx-8B",
               "error": f"bnb={str(bnb_exc)[:120]}, mlx={str(mlx_exc)[:120]}"}
        print(json.dumps(err), flush=True)
        sys.exit(1)

# Inspect actual device
try:
    first_param_device = str(next(model.parameters()).device) if hasattr(model, "parameters") else "unknown"
except StopIteration:
    first_param_device = "unknown"
hf_device_map = getattr(model, "hf_device_map", None)
if first_param_device.startswith("mps"):
    actual_device = "mps"
elif first_param_device.startswith("cpu"):
    actual_device = "cpu"
elif first_param_device.startswith("cuda"):
    actual_device = "cuda"
else:
    actual_device = first_param_device

rss_after_load = proc.memory_info().rss

prompt = (
    "You are a RAG evaluator. Context: Apple was founded in 1976. "
    "Question: When was Apple founded? Answer: Apple was founded in 1976. "
    "Is the answer faithful to the context? YES or NO."
)

def _run_inference():
    t0 = time.monotonic()
    if requested_backend == "mlx-lm":
        import mlx_lm
        mlx_lm.generate(model, tokenizer, prompt=prompt, max_tokens=20, verbose=False)
    else:
        import torch
        inp = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            model.generate(**inp, max_new_tokens=20)
    return round((time.monotonic() - t0) * 1000, 1)

warmup_latency_ms = _run_inference()

mps_alloc = None
if _mps_available:
    try:
        import torch
        mps_alloc = round(torch.mps.current_allocated_memory() / 1024**2, 1)
    except Exception:
        pass

ready_msg = {
    "status": "READY",
    "pid": os.getpid(),
    "model": "Patronus-Lynx-8B",
    "requested_backend": requested_backend,
    "actual_device": actual_device,
    "rss_after_load_mb": round(rss_after_load / 1024**2, 1),
    "mps_allocated_mb_after_warmup": mps_alloc,
    "warmup_latency_ms": warmup_latency_ms,
}
print(json.dumps(ready_msg), flush=True)

# Stdin command loop
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        cmd = json.loads(line)
    except json.JSONDecodeError:
        continue
    if cmd.get("cmd") == "shutdown":
        print(json.dumps({"result": "BYE", "pid": os.getpid()}), flush=True)
        sys.exit(0)
    elif cmd.get("cmd") == "infer":
        lat = _run_inference()
        cur_rss = proc.memory_info().rss
        mps_cur = None
        if _mps_available:
            try:
                import torch
                mps_cur = round(torch.mps.current_allocated_memory() / 1024**2, 1)
            except Exception:
                pass
        print(json.dumps({
            "result": "DONE",
            "latency_ms": lat,
            "rss_mb": round(cur_rss / 1024**2, 1),
            "mps_allocated_mb": mps_cur,
            "pid": os.getpid(),
        }), flush=True)
"""

_PROMETHEUS_RESIDENCY_WORKER = """
import json, sys, time, os
import psutil

proc = psutil.Process(os.getpid())
model_name = "prometheus-eval/prometheus-7b-v2.0"

_mps_available = False
actual_device = "unknown"
requested_backend = None

try:
    import torch
    if torch.backends.mps.is_available():
        _mps_available = True
except Exception:
    pass

model = None
tokenizer = None

try:
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    import torch
    bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(model_name, quantization_config=bnb_config, device_map="auto")
    requested_backend = "bitsandbytes-4bit"
except Exception as bnb_exc:
    try:
        import mlx_lm
        model, tokenizer = mlx_lm.load(model_name)
        requested_backend = "mlx-lm"
    except Exception as mlx_exc:
        err = {"status": "ERROR", "pid": os.getpid(), "model": "Prometheus-2-7B",
               "error": f"bnb={str(bnb_exc)[:120]}, mlx={str(mlx_exc)[:120]}"}
        print(json.dumps(err), flush=True)
        sys.exit(1)

# Inspect actual device
try:
    first_param_device = str(next(model.parameters()).device) if hasattr(model, "parameters") else "unknown"
except StopIteration:
    first_param_device = "unknown"
hf_device_map = getattr(model, "hf_device_map", None)
if first_param_device.startswith("mps"):
    actual_device = "mps"
elif first_param_device.startswith("cpu"):
    actual_device = "cpu"
elif first_param_device.startswith("cuda"):
    actual_device = "cuda"
else:
    actual_device = first_param_device

rss_after_load = proc.memory_info().rss

prompt = (
    "###Instruction:\\nWhat is the capital of France?\\n"
    "###Response:\\nThe capital of France is Paris.\\n"
    "###Reference (Score 5):\\nThe capital of France is Paris.\\n"
    "###Feedback: "
)

def _run_inference():
    t0 = time.monotonic()
    if requested_backend == "mlx-lm":
        import mlx_lm
        mlx_lm.generate(model, tokenizer, prompt=prompt, max_tokens=20, verbose=False)
    else:
        import torch
        inp = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            model.generate(**inp, max_new_tokens=20)
    return round((time.monotonic() - t0) * 1000, 1)

warmup_latency_ms = _run_inference()

mps_alloc = None
if _mps_available:
    try:
        import torch
        mps_alloc = round(torch.mps.current_allocated_memory() / 1024**2, 1)
    except Exception:
        pass

ready_msg = {
    "status": "READY",
    "pid": os.getpid(),
    "model": "Prometheus-2-7B",
    "requested_backend": requested_backend,
    "actual_device": actual_device,
    "rss_after_load_mb": round(rss_after_load / 1024**2, 1),
    "mps_allocated_mb_after_warmup": mps_alloc,
    "warmup_latency_ms": warmup_latency_ms,
}
print(json.dumps(ready_msg), flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        cmd = json.loads(line)
    except json.JSONDecodeError:
        continue
    if cmd.get("cmd") == "shutdown":
        print(json.dumps({"result": "BYE", "pid": os.getpid()}), flush=True)
        sys.exit(0)
    elif cmd.get("cmd") == "infer":
        lat = _run_inference()
        cur_rss = proc.memory_info().rss
        mps_cur = None
        if _mps_available:
            try:
                import torch
                mps_cur = round(torch.mps.current_allocated_memory() / 1024**2, 1)
            except Exception:
                pass
        print(json.dumps({
            "result": "DONE",
            "latency_ms": lat,
            "rss_mb": round(cur_rss / 1024**2, 1),
            "mps_allocated_mb": mps_cur,
            "pid": os.getpid(),
        }), flush=True)
"""

_HHEM_RESIDENCY_WORKER = """
import json, sys, time, os
import psutil

proc = psutil.Process(os.getpid())
model_name = "vectara/hallucination_evaluation_model"

_mps_available = False
actual_device = "unknown"

try:
    import torch
    if torch.backends.mps.is_available():
        _mps_available = True
except Exception:
    pass

try:
    from transformers import DebertaV2Tokenizer, AutoModelForSequenceClassification
    import torch
    tokenizer = DebertaV2Tokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name, trust_remote_code=True)
    model.eval()
except Exception as exc:
    err = {"status": "ERROR", "pid": os.getpid(), "model": "HHEM-2.1-Open", "error": str(exc)[:200]}
    print(json.dumps(err), flush=True)
    sys.exit(1)

try:
    first_param_device = str(next(model.parameters()).device)
except StopIteration:
    first_param_device = "unknown"
if first_param_device.startswith("mps"):
    actual_device = "mps"
elif first_param_device.startswith("cpu"):
    actual_device = "cpu"
else:
    actual_device = first_param_device

rss_after_load = proc.memory_info().rss

pair = [["The capital of France is Paris.", "France's capital is Paris."]]

def _run_inference():
    t0 = time.monotonic()
    with torch.no_grad():
        inp = tokenizer.batch_encode_plus(pair, return_tensors="pt", truncation=True, max_length=512)
        logits = model(**inp).logits.squeeze(dim=1)
        torch.sigmoid(logits).item()
    return round((time.monotonic() - t0) * 1000, 1)

warmup_latency_ms = _run_inference()

mps_alloc = None
if _mps_available:
    try:
        import torch
        mps_alloc = round(torch.mps.current_allocated_memory() / 1024**2, 1)
    except Exception:
        pass

ready_msg = {
    "status": "READY",
    "pid": os.getpid(),
    "model": "HHEM-2.1-Open",
    "requested_backend": "transformers-deberta-v2",
    "actual_device": actual_device,
    "rss_after_load_mb": round(rss_after_load / 1024**2, 1),
    "mps_allocated_mb_after_warmup": mps_alloc,
    "warmup_latency_ms": warmup_latency_ms,
}
print(json.dumps(ready_msg), flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        cmd = json.loads(line)
    except json.JSONDecodeError:
        continue
    if cmd.get("cmd") == "shutdown":
        print(json.dumps({"result": "BYE", "pid": os.getpid()}), flush=True)
        sys.exit(0)
    elif cmd.get("cmd") == "infer":
        lat = _run_inference()
        cur_rss = proc.memory_info().rss
        mps_cur = None
        if _mps_available:
            try:
                import torch
                mps_cur = round(torch.mps.current_allocated_memory() / 1024**2, 1)
            except Exception:
                pass
        print(json.dumps({
            "result": "DONE",
            "latency_ms": lat,
            "rss_mb": round(cur_rss / 1024**2, 1),
            "mps_allocated_mb": mps_cur,
            "pid": os.getpid(),
        }), flush=True)
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_vm_stat(label: str) -> dict[str, Any]:
    vm_stat_path = "/usr/bin/vm_stat"
    if not os.path.exists(vm_stat_path):
        return {"label": label, "error": "vm_stat not available"}
    try:
        r = subprocess.run([vm_stat_path], capture_output=True, text=True, timeout=5)
        raw = r.stdout
    except Exception as exc:
        return {"label": label, "error": str(exc)}

    page_size = 16384
    for line in raw.splitlines():
        if "page size of" in line:
            try:
                page_size = int(line.split("page size of")[1].split("bytes")[0].strip())
            except (ValueError, IndexError):
                pass

    page_fields = [
        ("Pages free:", "pages_free"),
        ("Pages active:", "pages_active"),
        ("Pages inactive:", "pages_inactive"),
        ("Pages wired down:", "pages_wired_down"),
        ("Pages occupied by compressor:", "pages_occupied_by_compressor"),
    ]
    counter_fields = [("Swapouts:", "swapouts")]

    parsed_pages: dict[str, int] = {}
    parsed_counters: dict[str, int] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        for key, field in page_fields:
            if stripped.startswith(key):
                try:
                    parsed_pages[field] = int(stripped.split(":")[1].strip().rstrip("."))
                except (ValueError, IndexError):
                    pass
        for key, field in counter_fields:
            if stripped.startswith(key):
                try:
                    parsed_counters[field] = int(stripped.split(":")[1].strip().rstrip("."))
                except (ValueError, IndexError):
                    pass

    parsed_mb = {k: round(v * page_size / 1024**2, 1) for k, v in parsed_pages.items()}
    return {
        "label": label,
        "page_size_bytes": page_size,
        "parsed_pages": parsed_pages,
        "parsed_mb": parsed_mb,
        "parsed_counters": parsed_counters,
    }


def _mps_snapshot() -> dict[str, Any]:
    try:
        import torch
        if torch.backends.mps.is_available():
            return {
                "mps_allocated_mb": round(torch.mps.current_allocated_memory() / 1024**2, 1),
                "mps_driver_mb": round(torch.mps.driver_allocated_memory() / 1024**2, 1),
            }
    except Exception:
        pass
    return {"mps_allocated_mb": None, "mps_driver_mb": None}


def _proc_rss_mb(pid: int) -> float | None:
    try:
        return round(psutil.Process(pid).memory_info().rss / 1024**2, 1)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _wait_for_ready(proc: "subprocess.Popen[bytes]", model_label: str, timeout_s: float = 600.0) -> dict[str, Any]:
    """Read lines from proc.stdout until a JSON line with status=READY appears."""
    deadline = time.monotonic() + timeout_s
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise RuntimeError(f"{model_label} process exited before READY (code {proc.returncode})")
            continue
        try:
            msg = json.loads(line.decode().strip())
        except json.JSONDecodeError:
            continue
        status = msg.get("status")
        if status == "READY":
            return msg
        if status == "ERROR":
            raise RuntimeError(f"{model_label} reported ERROR: {msg.get('error')}")
    raise TimeoutError(f"{model_label} did not reach READY within {timeout_s}s")


def _send_cmd(proc: "subprocess.Popen[bytes]", cmd: dict[str, Any], timeout_s: float = 300.0) -> dict[str, Any]:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write((json.dumps(cmd) + "\n").encode())
    proc.stdin.flush()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise RuntimeError(f"Process exited while waiting for cmd response (code {proc.returncode})")
            continue
        try:
            return json.loads(line.decode().strip())
        except json.JSONDecodeError:
            continue
    raise TimeoutError(f"No response to {cmd} within {timeout_s}s")


def _spawn_worker(script: str, python: str) -> "subprocess.Popen[bytes]":
    env = {**os.environ, "TOKENIZERS_PARALLELISM": "false", "HF_DATASETS_DISABLE_PROGRESS_BARS": "1"}
    return subprocess.Popen(
        [python, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,  # inherit so model loading progress is visible
        env=env,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(skip_hhem_stretch: bool = False) -> None:
    python = sys.executable
    hhem_python = str(_HHEM_VENV_PYTHON)
    hhem_available = pathlib.Path(hhem_python).exists()

    steps: list[dict[str, Any]] = []
    hard_gates: dict[str, Any] = {
        "lynx_reached_ready": False,
        "prometheus_reached_ready": False,
        "lynx_not_killed_by_signal": None,
        "prometheus_not_killed_by_signal": None,
        "lynx_infer_after_prometheus_loaded": False,
        "prometheus_infer_after_both_loaded": False,
    }

    def _step(label: str, data: dict[str, Any]) -> None:
        entry = {"step": label, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **data}
        steps.append(entry)
        print(f"[{label}] {json.dumps({k: v for k, v in data.items() if k not in ('vm_stat',)})}", file=sys.stderr)

    # Step 1: baseline
    vm_baseline = _capture_vm_stat("baseline")
    mps_base = _mps_snapshot()
    sys_mem = psutil.virtual_memory()
    _step("1_baseline", {
        "vm_stat": vm_baseline,
        "mps": mps_base,
        "system_available_mb": round(sys_mem.available / 1024**2, 1),
    })

    proc_a: subprocess.Popen[bytes] | None = None
    proc_b: subprocess.Popen[bytes] | None = None
    proc_c: subprocess.Popen[bytes] | None = None

    lynx_warmup_lat: float | None = None
    lynx_second_lat: float | None = None
    prometheus_warmup_lat: float | None = None
    prometheus_second_lat: float | None = None
    hhem_stretch_result: dict[str, Any] | None = None

    try:
        # Step 2: spawn Lynx
        print("Spawning Lynx worker...", file=sys.stderr)
        proc_a = _spawn_worker(_LYNX_RESIDENCY_WORKER, python)

        # Step 3: wait for Lynx READY
        ready_a = _wait_for_ready(proc_a, "Lynx", timeout_s=600.0)
        hard_gates["lynx_reached_ready"] = True
        vm_one = _capture_vm_stat("one_model_resident")
        rss_a = _proc_rss_mb(ready_a["pid"])
        lynx_warmup_lat = ready_a.get("warmup_latency_ms")
        _step("3_lynx_ready", {
            "ready_msg": ready_a,
            "rss_a_mb": rss_a,
            "vm_stat": vm_one,
        })

        # Step 4: spawn Prometheus
        print("Spawning Prometheus worker...", file=sys.stderr)
        proc_b = _spawn_worker(_PROMETHEUS_RESIDENCY_WORKER, python)

        # Step 5: wait for Prometheus READY
        ready_b = _wait_for_ready(proc_b, "Prometheus", timeout_s=600.0)
        hard_gates["prometheus_reached_ready"] = True
        vm_two = _capture_vm_stat("two_models_resident")
        rss_a2 = _proc_rss_mb(ready_a["pid"])
        rss_b = _proc_rss_mb(ready_b["pid"])
        prometheus_warmup_lat = ready_b.get("warmup_latency_ms")
        _step("5_prometheus_ready", {
            "ready_msg": ready_b,
            "rss_a_mb": rss_a2,
            "rss_b_mb": rss_b,
            "vm_stat": vm_two,
        })

        # Step 6: infer on Lynx
        print("Sending infer to Lynx...", file=sys.stderr)
        t6 = time.monotonic()
        resp_a = _send_cmd(proc_a, {"cmd": "infer"})
        vm_after_lynx_infer = _capture_vm_stat("after_lynx_infer")
        lynx_second_lat = resp_a.get("latency_ms")
        _step("6_lynx_infer", {"response": resp_a, "vm_stat": vm_after_lynx_infer})
        if resp_a.get("result") == "DONE":
            hard_gates["lynx_infer_after_prometheus_loaded"] = True

        # Step 7: infer on Prometheus
        print("Sending infer to Prometheus...", file=sys.stderr)
        resp_b = _send_cmd(proc_b, {"cmd": "infer"})
        vm_after_prom_infer = _capture_vm_stat("after_prometheus_infer")
        prometheus_second_lat = resp_b.get("latency_ms")
        _step("7_prometheus_infer", {"response": resp_b, "vm_stat": vm_after_prom_infer})
        if resp_b.get("result") == "DONE":
            hard_gates["prometheus_infer_after_both_loaded"] = True

        # Step 7.5 stretch: HHEM as subprocess C (only if Task 1 succeeded and not skipped)
        if not skip_hhem_stretch and hhem_available:
            print("Stretch: spawning HHEM worker via .venv-hhem...", file=sys.stderr)
            proc_c = _spawn_worker(_HHEM_RESIDENCY_WORKER, hhem_python)
            try:
                ready_c = _wait_for_ready(proc_c, "HHEM", timeout_s=300.0)
                vm_three = _capture_vm_stat("three_models_resident")
                rss_c = _proc_rss_mb(ready_c["pid"])
                _step("7.5_hhem_ready", {"ready_msg": ready_c, "rss_c_mb": rss_c, "vm_stat": vm_three})

                resp_c = _send_cmd(proc_c, {"cmd": "infer"})
                vm_after_hhem_infer = _capture_vm_stat("after_hhem_infer")
                _step("7.5_hhem_infer", {"response": resp_c, "vm_stat": vm_after_hhem_infer})
                hhem_stretch_result = {
                    "hhem_reached_ready": True,
                    "hhem_infer": resp_c.get("result") == "DONE",
                    "hhem_actual_device": ready_c.get("actual_device"),
                    "hhem_infer_latency_ms": resp_c.get("latency_ms"),
                    "hhem_rss_mb": rss_c,
                }
                _send_cmd(proc_c, {"cmd": "shutdown"})
                proc_c.wait(timeout=30)
            except Exception as stretch_exc:
                print(f"HHEM stretch failed: {stretch_exc}", file=sys.stderr)
                hhem_stretch_result = {"hhem_reached_ready": False, "error": str(stretch_exc)[:200]}

        # Step 8: shutdown both
        print("Sending shutdown to Lynx and Prometheus...", file=sys.stderr)
        try:
            _send_cmd(proc_a, {"cmd": "shutdown"}, timeout_s=30)
        except Exception:
            pass
        try:
            _send_cmd(proc_b, {"cmd": "shutdown"}, timeout_s=30)
        except Exception:
            pass
        proc_a.wait(timeout=60)
        proc_b.wait(timeout=60)

        hard_gates["lynx_not_killed_by_signal"] = proc_a.returncode != -signal.SIGKILL
        hard_gates["prometheus_not_killed_by_signal"] = proc_b.returncode != -signal.SIGKILL

        vm_final = _capture_vm_stat("after_shutdown")
        _step("9_shutdown", {
            "lynx_exit_code": proc_a.returncode,
            "prometheus_exit_code": proc_b.returncode,
            "vm_stat": vm_final,
        })

    except Exception as exc:
        print(f"ERROR during residency test: {exc}", file=sys.stderr)
        for p in [proc_a, proc_b, proc_c]:
            if p and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=10)
                except Exception:
                    pass
        steps.append({"step": "FATAL_ERROR", "error": str(exc)})

    finally:
        for p in [proc_a, proc_b, proc_c]:
            if p and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=10)
                except Exception:
                    pass

    # Compute swapouts delta
    swapouts_baseline = None
    swapouts_final = None
    for s in steps:
        vm = s.get("vm_stat") or {}
        counters = vm.get("parsed_counters") or {}
        if s["step"] == "1_baseline":
            swapouts_baseline = counters.get("swapouts")
        if s["step"] == "9_shutdown":
            swapouts_final = counters.get("swapouts")
    swapouts_delta = None
    if swapouts_baseline is not None and swapouts_final is not None:
        swapouts_delta = swapouts_final - swapouts_baseline

    # Latency ratios
    lynx_lat_ratio = None
    if lynx_warmup_lat and lynx_second_lat:
        lynx_lat_ratio = round(lynx_second_lat / lynx_warmup_lat, 2)
    prometheus_lat_ratio = None
    if prometheus_warmup_lat and prometheus_second_lat:
        prometheus_lat_ratio = round(prometheus_second_lat / prometheus_warmup_lat, 2)

    # Simultaneous residency verdict
    all_hard_gates_pass = (
        hard_gates["lynx_reached_ready"]
        and hard_gates["prometheus_reached_ready"]
        and hard_gates.get("lynx_not_killed_by_signal", False)
        and hard_gates.get("prometheus_not_killed_by_signal", False)
        and hard_gates["lynx_infer_after_prometheus_loaded"]
        and hard_gates["prometheus_infer_after_both_loaded"]
    )

    output: dict[str, Any] = {
        "run_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": "Apple Silicon, 24 GB unified memory",
        "simultaneous_residency": "DEMONSTRATED" if all_hard_gates_pass else "NOT DEMONSTRATED",
        "hard_gates": hard_gates,
        "diagnostics": {
            "swapouts_delta_boot_cumulative": swapouts_delta,
            "lynx_warmup_latency_ms": lynx_warmup_lat,
            "lynx_second_infer_latency_ms": lynx_second_lat,
            "lynx_latency_ratio_2nd_vs_warmup": lynx_lat_ratio,
            "prometheus_warmup_latency_ms": prometheus_warmup_lat,
            "prometheus_second_infer_latency_ms": prometheus_second_lat,
            "prometheus_latency_ratio_2nd_vs_warmup": prometheus_lat_ratio,
        },
        "hhem_stretch": hhem_stretch_result,
        "steps": steps,
        "notes": (
            "pages_free near zero is NOT a failure signal on Apple Silicon. macOS drives free pages "
            "toward zero while using compression, inactive-page reclamation, and purgeable memory. "
            "Swapouts in parsed_counters is a monotonic cumulative counter since boot."
        ),
    }

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")

    print(f"\nSimultaneous residency: {output['simultaneous_residency']}", file=sys.stderr)
    print(f"Hard gates: {hard_gates}", file=sys.stderr)
    print(f"Swapouts delta: {swapouts_delta}", file=sys.stderr)
    print(f"Lynx latency ratio: {lynx_lat_ratio}", file=sys.stderr)
    print(f"Prometheus latency ratio: {prometheus_lat_ratio}", file=sys.stderr)
    print(f"Output written to {_OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    skip = "--skip-hhem-stretch" in sys.argv
    main(skip_hhem_stretch=skip)
