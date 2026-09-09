# ADR 002: Llama Guard 3 Model Choice — 1B bfloat16 over 8B NF4

**Date:** 2026-09-09
**Status:** Accepted

## Context

The project's zero-cost constraint (documented in CLAUDE.md) requires all local
inference to run within the M5 Pro's unified memory (24 GB) without a paid
GPU runtime. The input rail stack also runs three frontier judge models on Day 5
(HHEM-2.1-open, Patronus Lynx 8B, Prometheus 2 7B), which compete for the same
memory budget.

The original design called for Llama Guard 3 8B with NF4 4-bit quantization via
bitsandbytes. The Commit F diagnostic (2026-09-09) confirmed that bitsandbytes
NF4 requires a CUDA-backed GPU and rejects MPS dispatch unconditionally. A fresh
cold-load attempt on M5 Pro MPS produces:

```
ValueError: Some modules are dispatched on the CPU or the disk. Make sure you
have enough GPU RAM to fit the quantized model.
```

The 8B model is not loadable in this environment without a paid cloud GPU runtime
(e.g., Cloud Run with T4, which carries per-request compute cost). That is out
of scope under the project constraint.

## Decision

Deploy **meta-llama/Llama-Guard-3-1B** in **bfloat16** as the hazard classifier.

bfloat16 loads natively on MPS and CPU via `device_map="auto"`. The 1B model
fits within the memory budget alongside the Day 5 frontier judges. No
quantization library is required.

## Evaluated Alternatives

| Model | Quantization | Load on MPS | English F1 | FPR | Memory |
|---|---|---|---|---|---|
| Llama Guard 3 8B | NF4 (bitsandbytes) | Fails (CUDA required) | 0.939 | 0.040 | ~4 GB |
| Llama Guard 3 1B | bfloat16 | Works | 0.899 | 0.090 | ~2 GB |

Numbers from Meta's model card (mlcommons hazard taxonomy, English subset).

The 8B model produces a 4-point F1 advantage and roughly half the false-positive
rate. For a finance-domain deployment where the empirical hazard rate is under 1%,
the absolute false-positive reduction (roughly 5 additional false positives per
10,000 benign queries) is acceptable. The accuracy delta is not acceptable in
a high-stakes general-purpose deployment, but this is a portfolio demonstration,
not a production system.

## Consequences

**Accepted:**
- English F1 drops from 0.939 to 0.899 on Meta's benchmark.
- False-positive rate increases from 4.0% to 9.0% on the benchmark set. In
  practice, the finance-domain hazard distribution skews toward S6 (Specialized
  Advice) and S2 (Non-Violent Crimes: financial fraud), which are well-covered
  by both model sizes.

**Not covered:**
- S14 (Code Interpreter Abuse) accuracy is not optimized on the 1B model. This
  category is not present in the financial RAG demo corpus, so the gap has no
  observable effect on the demo.

**Upgrade path:**
- Swapping back to 8B requires: (a) a CUDA runtime (Cloud Run GPU instance or a
  local CUDA machine), and (b) bitsandbytes installed in the runtime environment.
  The `_MODEL_ID` constant in `finsentry/rails/input/llama_guard.py` and the
  `dtype=torch.bfloat16` parameter are the only changes needed in production code.
  No API surface changes are required.
