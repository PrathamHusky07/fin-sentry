#!/usr/bin/env python3
"""Processes for the Day 10C load test: the downstream stub, an isolated gateway and the
flash consumer. The harness (scripts/load_test.py) starts and stops them.

Every launcher forces the model tier off, installs the egress tripwire, and writes an
attestation of its live objects that the harness checks before it generates any load.
Nothing here edits the product code: the gateway module is imported unchanged, and only
the event producer's topic is redirected so the load events never reach the live
rag-responses topic that the dashboards read.

    python scripts/load_test_stack.py stub --port 8011 --latency-ms 200
    python scripts/load_test_stack.py gateway --port 8010 --stub-url http://127.0.0.1:8011 \\
        --topic lt-rag-responses --attest <file> --spans <file>
    python scripts/load_test_stack.py consumer --topic lt-rag-responses --group lt-flash \\
        --verdict-topic lt-judge-verdicts --attest <file>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from load_test_lib import GEMINI_ENV_VARS, EgressTripwire  # noqa: E402


def isolate_env(**extra: str) -> None:
    """Switch the model tier off before any product module reads its settings. The
    credentials are set to empty strings, not removed, because load_dotenv() would
    otherwise restore them from .env."""
    for name in GEMINI_ENV_VARS:
        os.environ[name] = ""
    os.environ.update(
        {
            "GEMINI_MODE": "disabled",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "OTEL_EXPORTER": "none",
            **extra,
        }
    )


def gemini_env_present() -> list[str]:
    return [name for name in GEMINI_ENV_VARS if os.environ.get(name)]


def write_json(path: str, data: dict[str, Any]) -> None:
    tmp = Path(path + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)


# --- downstream stub --------------------------------------------------------


def run_stub(args: argparse.Namespace) -> None:
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI()
    served = {"requests": 0}

    @app.post("/v1/chat/completions")
    async def chat(body: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(args.latency_ms / 1000)
        served["requests"] += 1
        prompt = str(body["messages"][-1]["content"])
        found = re.search(r"\[chunk_id=([^\]]+)\]", prompt)
        answer: dict[str, Any] = {
            "answer": "The retrieved filing excerpt addresses this question.",
            "citations": [{"chunk_id": found.group(1), "quote": "excerpt"}] if found else [],
            "confidence": "medium" if found else "low",
        }
        return {"choices": [{"message": {"role": "assistant", "content": json.dumps(answer)}}]}

    @app.get("/stats")
    async def stats() -> dict[str, int]:
        return served

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


# --- isolated gateway -------------------------------------------------------


def run_gateway(args: argparse.Namespace) -> None:
    isolate_env(DOWNSTREAM_URL=args.stub_url, KAFKA_MODE="kafka")
    tripwire = EgressTripwire()
    tripwire.install()

    from opentelemetry import trace
    from opentelemetry.sdk.trace import SpanProcessor, TracerProvider

    class SpanRecorder(SpanProcessor):  # type: ignore[misc]
        """One JSON line per finished span: the per-stage latency record."""

        def __init__(self, path: str) -> None:
            self._file = open(path, "a", buffering=1)

        def on_end(self, span: Any) -> None:
            ms = (span.end_time - span.start_time) / 1e6
            line = {"n": span.name, "ms": round(ms, 2), "t": span.end_time / 1e9}
            self._file.write(json.dumps(line) + "\n")

        def shutdown(self) -> None:
            self._file.close()

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            self._file.flush()
            return True

    # Installed first, so the gateway's own configure_tracer_provider call is a no-op.
    provider = TracerProvider()
    provider.add_span_processor(SpanRecorder(args.spans))
    trace.set_tracer_provider(provider)

    import uvicorn

    import finsentry.gateway.main as gw
    from finsentry.events.producer import RagEventProducer

    gw.RagEventProducer = lambda **kw: RagEventProducer(topic=args.topic, **kw)  # type: ignore[misc,assignment]

    async def serve() -> None:
        server = uvicorn.Server(
            uvicorn.Config(gw.app, host="127.0.0.1", port=args.port, log_level="warning")
        )
        task = asyncio.create_task(server.serve())
        while not server.started and not task.done():
            await asyncio.sleep(0.2)
        if task.done():
            await task
            return
        rail, producer = gw._faithfulness_rail, gw._rag_event_producer
        write_json(
            args.attest,
            {
                "pid": os.getpid(),
                "port": args.port,
                "faithfulness_mode": getattr(rail, "_mode", None),
                "faithfulness_enabled": getattr(rail, "_enabled", None),
                "faithfulness_client_present": getattr(rail, "_client", True) is not None,
                "gemini_env_present": gemini_env_present(),
                "downstream_url": gw._DOWNSTREAM_URL,
                "producer_mode": producer.mode if producer else None,
                "producer_topic": getattr(producer, "_topic", None),
                "tripwire_installed": tripwire.installed,
                "tripwire_hits": list(tripwire.hits),
                "hf_offline": os.environ.get("HF_HUB_OFFLINE") == "1",
            },
        )
        await task

    # uvicorn re-raises the signal it caught once it has shut down. A handler that does
    # nothing keeps the process alive long enough to write the final attestation below.
    signal.signal(signal.SIGTERM, lambda *_: None)
    try:
        asyncio.run(serve())
    finally:
        provider.force_flush()
        write_json(args.attest + ".final", {"tripwire_hits": list(tripwire.hits)})


# --- flash consumer ---------------------------------------------------------


def run_consumer(args: argparse.Namespace) -> None:
    isolate_env(
        KAFKA_TOPIC=args.topic,
        KAFKA_CONSUMER_GROUP=args.group,
        KAFKA_VERDICT_TOPIC=args.verdict_topic,
    )
    tripwire = EgressTripwire()
    tripwire.install()

    from finsentry.consumer import main as consumer_main
    from finsentry.judges.flash_judge import flash_judge_from_env

    # The same constructor and environment the consumer's own _run() uses.
    judge = flash_judge_from_env()
    write_json(
        args.attest,
        {
            "pid": os.getpid(),
            "judge_mode": getattr(judge, "_mode", None),
            "judge_client_present": getattr(judge, "_client", True) is not None,
            "gemini_env_present": gemini_env_present(),
            "topic": os.environ["KAFKA_TOPIC"],
            "group": os.environ["KAFKA_CONSUMER_GROUP"],
            "verdict_topic": os.environ["KAFKA_VERDICT_TOPIC"],
            "bootstrap": os.environ.get("KAFKA_BOOTSTRAP_SERVERS"),
            "tripwire_installed": tripwire.installed,
            "tripwire_hits": list(tripwire.hits),
        },
    )
    try:
        asyncio.run(consumer_main._run())
    finally:
        write_json(args.attest + ".final", {"tripwire_hits": list(tripwire.hits)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="role", required=True)
    stub = sub.add_parser("stub")
    stub.add_argument("--port", type=int, required=True)
    stub.add_argument("--latency-ms", type=float, default=200.0)
    gateway = sub.add_parser("gateway")
    gateway.add_argument("--port", type=int, required=True)
    gateway.add_argument("--stub-url", required=True)
    gateway.add_argument("--topic", required=True)
    gateway.add_argument("--attest", required=True)
    gateway.add_argument("--spans", required=True)
    consumer = sub.add_parser("consumer")
    consumer.add_argument("--topic", required=True)
    consumer.add_argument("--group", required=True)
    consumer.add_argument("--verdict-topic", required=True)
    consumer.add_argument("--attest", required=True)
    args = parser.parse_args()
    {"stub": run_stub, "gateway": run_gateway, "consumer": run_consumer}[args.role](args)


if __name__ == "__main__":
    main()
