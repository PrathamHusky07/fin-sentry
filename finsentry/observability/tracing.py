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

import opentelemetry.trace as _otel_trace
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
    span.set_attribute("app_trace_id", app_trace_id)
