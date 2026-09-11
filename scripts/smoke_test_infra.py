"""
Smoke test: verify Redpanda and RisingWave are reachable and functional.

Run with:
    python scripts/smoke_test_infra.py

Prerequisites:
    docker compose -f docker-compose.dev.yml up -d

The script produces a test event to Redpanda, reads it back, then queries
the RisingWave version. A warning is printed if RisingWave is v3.0.x because
that release has a known 5-hour crash bug in playground mode — the version
deployed in docker-compose.dev.yml. The bug affects long-running sessions; short
smoke tests complete before the window.

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid

# ---------------------------------------------------------------------------
# Config (mirrors docker-compose.dev.yml)
# ---------------------------------------------------------------------------
REDPANDA_BOOTSTRAP = "localhost:9092"
REDPANDA_TOPIC = "_smoke_test"
RISINGWAVE_HOST = "localhost"
RISINGWAVE_PORT = 4566
RISINGWAVE_USER = "root"
RISINGWAVE_DB = "dev"


# ---------------------------------------------------------------------------
# Redpanda round-trip
# ---------------------------------------------------------------------------


async def _check_redpanda() -> bool:
    """Produce a JSON event and consume it back. Returns True on success."""
    try:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # type: ignore[import-untyped]
    except ImportError:
        print("[REDPANDA] FAIL: aiokafka not installed (pip install aiokafka)")
        return False

    correlation_id = str(uuid.uuid4())
    payload = json.dumps({"smoke": True, "correlation_id": correlation_id}).encode()

    producer = AIOKafkaProducer(
        bootstrap_servers=REDPANDA_BOOTSTRAP,
        request_timeout_ms=5000,
    )
    try:
        await producer.start()
    except Exception as exc:
        print(f"[REDPANDA] FAIL: could not connect to {REDPANDA_BOOTSTRAP}: {exc}")
        return False

    try:
        await producer.send_and_wait(REDPANDA_TOPIC, payload)
    except Exception as exc:
        print(f"[REDPANDA] FAIL: produce error: {exc}")
        return False
    finally:
        await producer.stop()

    consumer = AIOKafkaConsumer(
        REDPANDA_TOPIC,
        bootstrap_servers=REDPANDA_BOOTSTRAP,
        auto_offset_reset="earliest",
        consumer_timeout_ms=5000,
        group_id=f"smoke-{uuid.uuid4()}",
    )
    try:
        await consumer.start()
    except Exception as exc:
        print(f"[REDPANDA] FAIL: consumer connect error: {exc}")
        return False

    try:
        deadline = time.monotonic() + 6.0
        async for msg in consumer:
            body = json.loads(msg.value.decode())
            if body.get("correlation_id") == correlation_id:
                print(
                    f"[REDPANDA] OK  round-trip in "
                    f"{int((time.monotonic() - (deadline - 6)) * 1000)} ms"
                )
                return True
            if time.monotonic() > deadline:
                break
        print("[REDPANDA] FAIL: timed out waiting for own message")
        return False
    except Exception as exc:
        print(f"[REDPANDA] FAIL: consume error: {exc}")
        return False
    finally:
        await consumer.stop()


# ---------------------------------------------------------------------------
# RisingWave version check
# ---------------------------------------------------------------------------


async def _check_risingwave() -> bool:
    """Connect via Postgres protocol and check version. Returns True if reachable."""
    try:
        import psycopg
    except ImportError:
        print("[RISINGWAVE] FAIL: psycopg not installed (pip install psycopg)")
        return False

    dsn = (
        f"host={RISINGWAVE_HOST} port={RISINGWAVE_PORT} "
        f"user={RISINGWAVE_USER} dbname={RISINGWAVE_DB}"
    )
    try:
        conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    except Exception as exc:
        print(f"[RISINGWAVE] FAIL: could not connect to {RISINGWAVE_HOST}:{RISINGWAVE_PORT}: {exc}")
        return False

    try:
        row = await (await conn.execute("SELECT version();")).fetchone()
        version_str = str(row[0]) if row else "unknown"
        print(f"[RISINGWAVE] OK  version={version_str!r}")

        # v3.0.x has a known playground-mode crash at ~5 hours uptime.
        # The docker-compose.dev.yml pins v3.0.3. Flag it but do not fail.
        if ".0." in version_str and version_str.startswith("v3") or "3.0." in version_str:
            print(
                "[RISINGWAVE] WARN: v3.0.x detected. Known playground crash after ~5 hours. "
                "Restart the container before long sessions: "
                "docker compose -f docker-compose.dev.yml restart finsentry-risingwave"
            )
        return True
    except Exception as exc:
        print(f"[RISINGWAVE] FAIL: query error: {exc}")
        return False
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> int:
    print("=== fin-sentry infrastructure smoke test ===")
    redpanda_ok = await _check_redpanda()
    risingwave_ok = await _check_risingwave()
    print()
    if redpanda_ok and risingwave_ok:
        print("All checks passed.")
        return 0
    else:
        checks = [("Redpanda", redpanda_ok), ("RisingWave", risingwave_ok)]
        failed = [name for name, ok in checks if not ok]
        print(f"Failed: {', '.join(failed)}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
