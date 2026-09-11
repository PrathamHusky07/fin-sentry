"""Tests for finsentry.observability.tracing.

Key concern: app_trace_id (UUID4) and OTel trace_id (128-bit hex) are distinct
identifiers with different formats, different audiences, and different lifecycle
owners. These tests lock in that separation.
"""
from __future__ import annotations

import re
import uuid

import opentelemetry.trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan

from finsentry.observability.tracing import configure_tracer_provider, get_tracer, set_app_trace_id


def _make_in_memory_tracer() -> tuple[object, InMemorySpanExporter]:
    """Return a (tracer, exporter) pair backed by an in-memory span store."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    return tracer, exporter


def test_get_tracer_returns_opentelemetry_tracer() -> None:
    """get_tracer() returns an object that can start spans."""
    from opentelemetry.trace import Tracer

    tracer = get_tracer("finsentry.test")
    assert isinstance(tracer, Tracer)


def test_set_app_trace_id_records_attribute_on_span() -> None:
    """set_app_trace_id() writes the UUID string as a span attribute 'app_trace_id'."""
    tracer, exporter = _make_in_memory_tracer()
    app_id = str(uuid.uuid4())

    with tracer.start_as_current_span("test.op") as span:  # type: ignore[attr-defined]
        set_app_trace_id(span, app_id)  # type: ignore[arg-type]

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].attributes is not None
    assert finished[0].attributes.get("app_trace_id") == app_id


def test_otel_trace_id_is_32_hex_chars_without_hyphens() -> None:
    """OTel trace_id is a 128-bit integer formatted as 32 lowercase hex chars, no hyphens."""
    tracer, exporter = _make_in_memory_tracer()

    with tracer.start_as_current_span("test.op"):  # type: ignore[attr-defined]
        pass

    finished = exporter.get_finished_spans()
    otel_trace_id = format(finished[0].context.trace_id, "032x")
    # Must be exactly 32 hex chars, no hyphens, all lowercase hex
    assert re.fullmatch(r"[0-9a-f]{32}", otel_trace_id), (
        f"OTel trace_id {otel_trace_id!r} is not 32 lowercase hex chars"
    )


def test_app_trace_id_is_uuid4_not_otel_format() -> None:
    """app_trace_id is UUID4 (36 chars with hyphens), structurally different from OTel trace_id."""
    _uuid4_re = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    tracer, exporter = _make_in_memory_tracer()
    app_id = str(uuid.uuid4())

    with tracer.start_as_current_span("test.op") as span:  # type: ignore[attr-defined]
        set_app_trace_id(span, app_id)  # type: ignore[arg-type]

    finished = exporter.get_finished_spans()
    otel_trace_id = format(finished[0].context.trace_id, "032x")
    recorded_app_id = finished[0].attributes["app_trace_id"]

    # UUID4 has hyphens; OTel trace_id does not
    assert "-" in str(recorded_app_id), "app_trace_id must contain hyphens (UUID4 format)"
    assert "-" not in otel_trace_id, "OTel trace_id must not contain hyphens"
    assert _uuid4_re.match(str(recorded_app_id)), "app_trace_id must match UUID4 pattern"
    # The two IDs are always different values (extremely high probability for random UUIDs)
    assert str(recorded_app_id).replace("-", "") != otel_trace_id


def test_set_app_trace_id_no_op_on_non_recording_span() -> None:
    """set_app_trace_id() does not raise when called on a NonRecordingSpan."""
    non_recording = NonRecordingSpan(otel_trace.INVALID_SPAN_CONTEXT)
    # Must not raise; the is_recording() guard should prevent the set_attribute call.
    set_app_trace_id(non_recording, str(uuid.uuid4()))


def test_configure_tracer_provider_none_creates_spans_no_export() -> None:
    """configure_tracer_provider('none') installs a provider with no exporter.

    Spans created by get_tracer() after the call are recording spans but produce
    no export side effects — verified by observing no exception during span creation.
    """
    configure_tracer_provider("none")
    tracer = otel_trace.get_tracer("test.none")
    with tracer.start_as_current_span("test.span") as span:
        # The span should be a recording span (TracerProvider is installed)
        # but has no exporter. We just verify it does not raise.
        assert span is not None


def test_configure_tracer_provider_console_installs_console_exporter() -> None:
    """configure_tracer_provider('console') installs without raising."""
    # This only verifies no exception is raised during installation.
    # Actual console output is not asserted (stdout is not captured in this test).
    configure_tracer_provider("console")
    tracer = otel_trace.get_tracer("test.console")
    with tracer.start_as_current_span("test.span") as span:
        assert span is not None
    # Restore to none so subsequent tests are not affected by console spam.
    configure_tracer_provider("none")
