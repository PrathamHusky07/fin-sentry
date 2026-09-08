from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

_provider: TracerProvider | None = None


def _ensure_provider() -> None:
    global _provider
    if _provider is not None:
        return
    _provider = TracerProvider()
    # SimpleSpanProcessor is synchronous — no background flush thread that races
    # with stdout closing at process exit. Replace with BatchSpanProcessor +
    # OTLPSpanExporter when the collector is wired on Day 7.
    _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(_provider)


def get_tracer(name: str = "finsentry") -> trace.Tracer:
    _ensure_provider()
    return trace.get_tracer(name)
