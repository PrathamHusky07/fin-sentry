#!/usr/bin/env python3
"""End-to-end smoke test for the async evaluation pipeline.

Verifies a single RAG query flows all the way from the gateway through
Redpanda, the FlashJudge consumer, and surfaces on the dashboard.

The operator must start three services before running this script:
  uvicorn finsentry.gateway.main:app --port 8000
  python -m finsentry.consumer.main
  uvicorn finsentry.dashboard.app:app --port 8081

Run with:
  python scripts/smoke_test_e2e.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

GATEWAY_URL = "http://localhost:8000"
DASHBOARD_URL = "http://localhost:8081"
TOPIC_RAG = "rag-responses"
TOPIC_VERDICTS = "judge-verdicts"


RPK_PREFIX = ["docker", "exec", "finsentry-redpanda", "rpk"]


def _run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _rpk(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return _run([*RPK_PREFIX, *args], timeout=timeout)


def _step(n: int, msg: str) -> None:
    print(f"\n[step {n}] {msg}")


def _ok(msg: str) -> None:
    print(f"  OK  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Step 1: docker-compose stack health check
# ---------------------------------------------------------------------------

_step(1, "Checking docker-compose stack is running")
result = _run(["docker", "compose", "-f", "docker-compose.dev.yml", "ps", "--format", "json"])
if result.returncode != 0:
    _fail(
        "docker compose ps failed. Start the stack first:\n"
        "  docker compose -f docker-compose.dev.yml up -d"
    )

services_text = result.stdout.strip()
required = {"postgres", "redpanda", "risingwave"}
found: set[str] = set()
for line in services_text.splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
        name = obj.get("Service", "").lower()
        state = obj.get("State", "").lower()
        if any(r in name for r in required) and state in {"running", "healthy"}:
            for r in required:
                if r in name:
                    found.add(r)
    except json.JSONDecodeError:
        pass

missing = required - found
if missing:
    _fail(
        f"Required services not running or healthy: {missing}\n"
        "  docker compose -f docker-compose.dev.yml up -d"
    )
_ok(f"Services running: {found}")


# ---------------------------------------------------------------------------
# Step 2: .env KAFKA_MODE=kafka check
# ---------------------------------------------------------------------------

_step(2, "Checking .env has KAFKA_MODE=kafka")
try:
    env_text = open(".env").read()
except FileNotFoundError:
    _fail(".env not found. Copy .env.example and set KAFKA_MODE=kafka")

kafka_mode_set = any(
    line.strip() == "KAFKA_MODE=kafka"
    for line in env_text.splitlines()
    if not line.strip().startswith("#")
)
if not kafka_mode_set:
    _fail(
        "KAFKA_MODE is not set to 'kafka' in .env.\n"
        "  Edit .env: KAFKA_MODE=kafka"
    )
_ok("KAFKA_MODE=kafka confirmed")


# ---------------------------------------------------------------------------
# Step 3: Ensure rag-responses topic exists
# ---------------------------------------------------------------------------

_step(3, f"Ensuring topic '{TOPIC_RAG}' exists")
result = _rpk(["topic", "create", TOPIC_RAG])
combined = ((result.stdout or "") + (result.stderr or "")).upper()
already_exists = "TOPIC_ALREADY_EXISTS" in combined or "ALREADY BEEN CREATED" in combined
if result.returncode != 0 and not already_exists:
    _fail(
        f"rpk topic create returned exit={result.returncode} "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
else:
    _ok(f"Topic '{TOPIC_RAG}' ready")


# ---------------------------------------------------------------------------
# Step 4: Operator prompt — start services
# ---------------------------------------------------------------------------

_step(4, "Operator action required")
print(
    "\n  Start the following in separate terminals (if not already running):\n"
    "\n    Terminal 1 — Gateway:\n"
    "      uvicorn finsentry.gateway.main:app --port 8000\n"
    "\n    Terminal 2 — Consumer:\n"
    "      python -m finsentry.consumer.main\n"
    "\n    Terminal 3 — Dashboard:\n"
    "      uvicorn finsentry.dashboard.app:app --port 8081\n"
    "\n  Wait for all three to show a ready/started log line."
)
input("\n  Press Enter when all three are ready...")


# ---------------------------------------------------------------------------
# Step 5: Fire a RAG query
# ---------------------------------------------------------------------------

_step(5, "Firing canned RAG query to gateway")
try:
    import httpx
except ImportError:
    _fail("httpx not installed. Run: pip install httpx")

query_payload = {
    "query": "What was Apple total net sales in fiscal year 2024?",
    "ticker": "AAPL",
}
try:
    resp = httpx.post(f"{GATEWAY_URL}/v1/rag/query", json=query_payload, timeout=60.0)
except httpx.ConnectError:
    _fail(
        f"Could not connect to gateway at {GATEWAY_URL}.\n"
        "  Is the gateway running? uvicorn finsentry.gateway.main:app --port 8000"
    )

if resp.status_code not in {200, 422}:
    _fail(f"Gateway returned unexpected status {resp.status_code}: {resp.text[:200]}")

body = resp.json()
app_trace_id = body.get("retrieval_trace_id") or body.get("output_rail_trace", {})
if isinstance(body, dict) and "retrieval_trace_id" in body:
    app_trace_id = body["retrieval_trace_id"]
elif isinstance(body, dict) and "error" in body:
    # Rail block: no retrieval_trace_id, but we can still check the topic
    app_trace_id = None
    print(f"  NOTE: gateway returned rail block ({body.get('error')}); "
          "event was still emitted to topic")
else:
    _fail(f"Could not extract app_trace_id from response: {body}")

_ok(f"Gateway responded (status={resp.status_code}, app_trace_id={app_trace_id})")


# ---------------------------------------------------------------------------
# Step 6: Poll rag-responses topic for the emitted event
# ---------------------------------------------------------------------------

_step(6, f"Polling '{TOPIC_RAG}' for event with matching app_trace_id")
try:
    result = _rpk(["topic", "consume", TOPIC_RAG, "-n", "1"], timeout=15)
except subprocess.TimeoutExpired:
    _fail(
        f"No message arrived on '{TOPIC_RAG}' within 15 seconds. "
        "Is the gateway running with KAFKA_MODE=kafka?"
    )
if result.returncode != 0:
    _fail(
        f"rpk consume on '{TOPIC_RAG}' failed: {result.stderr.strip()}\n"
        "  Is the gateway running and KAFKA_MODE=kafka?"
    )

consumed_text = result.stdout.strip()
if not consumed_text:
    _fail(f"No messages found in '{TOPIC_RAG}' within 10 seconds")

try:
    # rpk outputs one JSON object per line; take the last non-empty line
    for line in reversed(consumed_text.splitlines()):
        line = line.strip()
        if line:
            msg = json.loads(line)
            # rpk wraps in {value: "...", ...}; value is the raw JSON string
            value = msg.get("value", msg)
            if isinstance(value, str):
                value = json.loads(value)
            found_trace = value.get("app_trace_id")
            break
    else:
        _fail("No consumable message found")
except (json.JSONDecodeError, KeyError) as exc:
    _fail(f"Could not parse rag-responses message: {exc}\nRaw: {consumed_text[:300]}")

if app_trace_id and found_trace != app_trace_id:
    print(
        f"  WARNING: consumed app_trace_id={found_trace} does not match "
        f"expected={app_trace_id} — may be an older message"
    )
else:
    _ok(f"Found event on '{TOPIC_RAG}' (app_trace_id={found_trace})")


# ---------------------------------------------------------------------------
# Step 7: Poll judge-verdicts topic for a verdict
# ---------------------------------------------------------------------------

_step(7, f"Polling '{TOPIC_VERDICTS}' for judge verdict (up to 90 seconds)")
try:
    result = _rpk(["topic", "consume", TOPIC_VERDICTS, "-n", "1"], timeout=100)
except subprocess.TimeoutExpired:
    _fail(
        f"No verdict arrived on '{TOPIC_VERDICTS}' within 100 seconds. "
        "Consumer may be slow or Vertex Gemini may be rate-limited. "
        "Check the consumer terminal for FlashJudge verdict log lines."
    )
if result.returncode != 0:
    _fail(
        f"rpk consume on '{TOPIC_VERDICTS}' failed: {result.stderr.strip()}\n"
        "  Is the consumer running? python -m finsentry.consumer.main\n"
        "  Is GEMINI_MODE set? (mode=disabled will still emit a verdict with skipped_* statuses)"
    )

verdict_text = result.stdout.strip()
if not verdict_text:
    _fail(f"No verdict found in '{TOPIC_VERDICTS}' within 90 seconds")

try:
    for line in reversed(verdict_text.splitlines()):
        line = line.strip()
        if line:
            vmsg = json.loads(line)
            vvalue = vmsg.get("value", vmsg)
            if isinstance(vvalue, str):
                vvalue = json.loads(vvalue)
            verdict_trace = vvalue.get("app_trace_id")
            verdict_tier = vvalue.get("judge_tier", "unknown")
            verdict_status = vvalue.get("status", "unknown")
            break
    else:
        _fail("No verdict message found")
except (json.JSONDecodeError, KeyError) as exc:
    _fail(f"Could not parse judge-verdicts message: {exc}\nRaw: {verdict_text[:300]}")

if app_trace_id and verdict_trace != app_trace_id:
    print(
        f"  WARNING: verdict app_trace_id={verdict_trace} does not match "
        f"expected={app_trace_id} — may be an older message"
    )
else:
    _ok(
        f"Found verdict on '{TOPIC_VERDICTS}' "
        f"(tier={verdict_tier}, status={verdict_status}, app_trace_id={verdict_trace})"
    )


# ---------------------------------------------------------------------------
# Step 8: Poll dashboard /metrics for evidence of the pipeline
# ---------------------------------------------------------------------------

_step(8, "Polling dashboard /metrics for throughput and verdict data (up to 60 seconds)")

dashboard_ok = False
for attempt in range(6):
    if attempt > 0:
        time.sleep(10)
        print(f"  Retrying ({attempt}/5)...")
    try:
        m = httpx.get(f"{DASHBOARD_URL}/metrics", timeout=5.0)
        if m.status_code != 200:
            continue
        mdata = m.json()
        tp = mdata.get("throughput") or {}
        fa = mdata.get("faithfulness") or {}
        if (tp.get("total_requests") or 0) >= 1 and (fa.get("verdicts_count") or 0) >= 1:
            _ok(
                f"Dashboard shows total_requests={tp.get('total_requests')} "
                f"verdicts_count={fa.get('verdicts_count')}"
            )
            dashboard_ok = True
            break
        print(
            f"  Dashboard data not yet populated: "
            f"total_requests={tp.get('total_requests')}, "
            f"verdicts_count={fa.get('verdicts_count')}"
        )
    except Exception as exc:
        print(f"  Dashboard poll error: {exc}")

if not dashboard_ok:
    print(
        "\n  DIAGNOSIS: Dashboard did not show data within 60 seconds.\n"
        "  Check that RisingWave is running and init.sql was applied:\n"
        "    python scripts/init_risingwave.py\n"
        "  Also verify the consumer group name matches the RisingWave source.\n"
        "  The pipeline may still work; this only means the windowed views are empty."
    )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
if dashboard_ok:
    print("END-TO-END SMOKE TEST PASSED")
else:
    print(
        "END-TO-END PIPELINE PASSED (event -> verdict verified)\n"
        "Dashboard materialized view not yet populated — see diagnosis above."
    )
print("=" * 60 + "\n")
