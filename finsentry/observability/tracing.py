"""OTel tracer helpers for the finsentry gateway.

Two distinct identifiers travel with every request:

  app_trace_id  — UUID4 generated at handler entry, carried on Kafka events,
                  logs, and span attributes. 36 chars: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.

  OTel trace_id — 128-bit integer assigned by the TracerProvider, formatted as
                  32 lowercase hex chars with no hyphens. Recorded by the OTel
                  backend and used for distributed tracing across services that
                  share context propagation (W3C TraceContext).

The two serve different audiences. app_trace_id is the application-level
correlation key — queryable in Kafka, Postgres, and any log aggregator without
OTel participation. OTel trace_id is for the distributed tracing backend. They
coexist on every span via the 'app_trace_id' attribute.
"""
from __future__ import annotations

import os
from typing import Literal

import opentelemetry.trace as _otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span


def get_tracer(name: str = "finsentry.gateway") -> _otel_trace.Tracer:
    """Return the OTel tracer for the given instrumentation scope."""
    return _otel_trace.get_tracer(name)


def set_app_trace_id(span: Span, app_trace_id: str) -> None:
    """Set the application correlation ID as a span attribute.

    This records the app_trace_id (UUID4) on the OTel span so the two
    correlation systems — OTel trace_id and app_trace_id — are linked
    in the tracing backend without conflating their formats or semantics.
    """
    if span.is_recording():
        span.set_attribute("app_trace_id", app_trace_id)


def configure_tracer_provider(exporter: Literal["console", "otlp", "none"]) -> None:
    """Install a TracerProvider with the requested exporter.

    "console": install ConsoleSpanExporter via BatchSpanProcessor (dev-friendly).
    "otlp":    install OTLPSpanExporter via BatchSpanProcessor; endpoint from
               OTEL_EXPORTER_OTLP_ENDPOINT (default http://localhost:4317).
    "none":    install TracerProvider with no exporter — spans created but not exported.
    """
    provider = TracerProvider()

    if exporter == "console":
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: F401
            InMemorySpanExporter,
        )
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    elif exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))

    # "none" case: provider has no processor, spans are created but not exported

    _otel_trace.set_tracer_provider(provider)
