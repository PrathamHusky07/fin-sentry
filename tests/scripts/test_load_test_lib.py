"""Tests for scripts/load_test_lib.py: schedule, statistics, verdicts, isolation checks."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

# scripts/ is not a package; import via sys.path manipulation.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from load_test_lib import (  # noqa: E402, I001
    EgressTripwire,
    Record,
    ResourceLimits,
    Slo,
    arrival_offsets,
    consumer_attestation_problems,
    gateway_attestation_problems,
    has_headroom,
    is_blocked_host,
    parse_group_describe,
    parse_resources,
    percentile,
    reconcile,
    resource_breach,
    slo_violations,
    stage_stats,
)
from load_test_report import span_stats  # noqa: E402

STUB = {"stub_url": "http://127.0.0.1:8011", "topic": "lt-rag-responses"}
GOOD_GATEWAY = {
    "faithfulness_mode": "disabled",
    "faithfulness_enabled": False,
    "faithfulness_client_present": False,
    "gemini_env_present": [],
    "downstream_url": "http://127.0.0.1:8011",
    "producer_mode": "kafka",
    "producer_topic": "lt-rag-responses",
    "tripwire_installed": True,
    "tripwire_hits": [],
    "hf_offline": True,
}
CONSUMER_EXPECT = {"topic": "lt-rag-responses", "group": "lt-flash", "verdict_topic": "lt-verdicts"}
GOOD_CONSUMER = {
    "judge_mode": "disabled",
    "judge_client_present": False,
    "gemini_env_present": [],
    "topic": "lt-rag-responses",
    "group": "lt-flash",
    "verdict_topic": "lt-verdicts",
    "tripwire_installed": True,
    "tripwire_hits": [],
}


def test_arrival_offsets_are_evenly_spaced_and_count_matches_the_offered_rate() -> None:
    offsets = arrival_offsets(4.0, 3.0)
    assert len(offsets) == 12
    assert offsets[:3] == [0.0, 0.25, 0.5]
    assert offsets[-1] < 3.0


def test_percentile_uses_nearest_rank() -> None:
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 99) == 99
    assert percentile([], 99) is None


def _record(seq: int, sched: float, done: float | None, status: int | None) -> Record:
    return Record(seq, sched, sent_s=sched, done_s=done, status=status)


def test_stage_stats_keep_offered_and_achieved_apart_and_count_failures() -> None:
    records = [_record(i, i * 0.5, i * 0.5 + 1.0, 200) for i in range(8)]  # 8 ok, 1 s each
    blocked = _record(8, 4.0, 5.0, 403)
    blocked.block_rail = "check hazard taxonomy"
    records.append(blocked)
    records.append(_record(9, 4.5, None, None))  # sent, never answered
    stats = stage_stats(records, duration_s=5.0)
    assert stats["offered_requests"] == 10 and stats["offered_rps"] == 2.0
    assert stats["ok_200"] == 8 and stats["no_response"] == 1
    assert stats["status_counts"] == {"200": 8, "403": 1}
    assert stats["blocked_by_rail"] == {"check hazard taxonomy": 1}
    assert stats["error_rate"] == 0.2
    assert stats["latency_ms_all_responses"]["p50"] == 1000.0
    # Achieved throughput is derived from completions, not from the offered rate.
    assert stats["achieved_rps_busy_span"] == pytest.approx(
        8 / 4.5, rel=0.01
    )  # first send 0 s, last 200 at 4.5 s


def test_latency_is_measured_from_the_scheduled_time() -> None:
    late = Record(0, scheduled_s=0.0, sent_s=2.0, done_s=3.0, status=200)
    assert stage_stats([late], 1.0)["latency_ms_all_responses"]["p50"] == 3000.0


def _stats(p95: float, p99: float, error_rate: float) -> dict[str, object]:
    return {
        "latency_ms_all_responses": {"p50": 1.0, "p95": p95, "p99": p99, "max": p99},
        "error_rate": error_rate,
    }


def test_slo_violations_name_each_breached_limit() -> None:
    slo = Slo(p95_ms=3000, p99_ms=5000, max_error_rate=0.01)
    assert slo_violations(_stats(2000, 4000, 0.0), slo) == []
    breached = slo_violations(_stats(3500, 6000, 0.05), slo)
    assert len(breached) == 3
    assert slo_violations({"latency_ms_all_responses": {"p95": None}, "error_rate": 1.0}, slo)


def test_headroom_requires_the_slo_and_a_p99_at_half_the_budget() -> None:
    slo = Slo()
    assert has_headroom(_stats(1000, 2400, 0.0), slo)
    assert not has_headroom(_stats(1000, 2600, 0.0), slo)
    assert not has_headroom(_stats(1000, 2000, 0.5), slo)


def test_resource_readings_parse_and_breaches_are_named() -> None:
    now = parse_resources(
        "System-wide memory free percentage: 43%",
        "vm.swapusage: total = 22528.00M  used = 21377.56M  free = 1150.44M  (encrypted)",
    )
    assert now["mem_free_pct"] == 43.0 and now["swap_free_mb"] == 1150.44
    limits = ResourceLimits()
    assert resource_breach(now, now, limits) is None
    assert "free memory" in (resource_breach({**now, "mem_free_pct": 12.0}, now, limits) or "")
    assert (
        resource_breach({**now, "swap_free_mb": 10.0}, now, limits) is None
    )  # growth, not headroom
    grown = {**now, "swap_used_mb": now["swap_used_mb"] + 2000}
    assert "swap grew" in (resource_breach(grown, now, limits) or "")
    with pytest.raises(ValueError):
        parse_resources("garbage", "garbage")


def test_blocked_hosts_cover_google_api_hosts_only() -> None:
    assert is_blocked_host("aiplatform.googleapis.com")
    assert is_blocked_host("generativelanguage.googleapis.com.")
    assert is_blocked_host("metadata.google.internal")
    assert not is_blocked_host("localhost")
    assert not is_blocked_host("notgoogleapis.com")


def test_the_tripwire_blocks_and_records_a_google_api_lookup() -> None:
    tripwire = EgressTripwire()
    tripwire.install()
    try:
        with pytest.raises(OSError, match="tripwire"):
            socket.getaddrinfo("aiplatform.googleapis.com", 443)
        assert socket.getaddrinfo("localhost", 80)  # local names still resolve
    finally:
        tripwire.uninstall()
    assert tripwire.hits == ["aiplatform.googleapis.com"]


def test_a_clean_gateway_attestation_has_no_problems() -> None:
    assert gateway_attestation_problems(GOOD_GATEWAY, STUB) == []


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("faithfulness_mode", "vertex", "not disabled"),
        ("faithfulness_enabled", True, "reports enabled"),
        ("faithfulness_client_present", True, "model client"),
        ("gemini_env_present", ["GEMINI_API_KEY"], "credentials"),
        ("downstream_url", "http://localhost:11434", "local stub"),
        ("producer_topic", "rag-responses", "another topic"),
        ("producer_mode", "disabled", "kafka mode"),
        ("tripwire_installed", False, "not installed"),
        ("tripwire_hits", ["aiplatform.googleapis.com"], "already fired"),
        ("hf_offline", False, "offline"),
    ],
)
def test_each_gateway_isolation_break_is_reported(field: str, value: object, fragment: str) -> None:
    problems = gateway_attestation_problems({**GOOD_GATEWAY, field: value}, STUB)
    assert len(problems) == 1 and fragment in problems[0]


def test_a_missing_gateway_attestation_field_fails_closed() -> None:
    assert len(gateway_attestation_problems({}, STUB)) == 10


def test_consumer_attestation_fails_closed_on_a_live_judge_or_the_real_topic() -> None:
    assert consumer_attestation_problems(GOOD_CONSUMER, CONSUMER_EXPECT) == []
    live = {**GOOD_CONSUMER, "judge_mode": "vertex", "judge_client_present": True}
    assert len(consumer_attestation_problems(live, CONSUMER_EXPECT)) == 2
    real_topic = {**GOOD_CONSUMER, "topic": "rag-responses", "group": "finsentry-rag-flash-judge"}
    assert len(consumer_attestation_problems(real_topic, CONSUMER_EXPECT)) == 2
    assert len(consumer_attestation_problems({}, CONSUMER_EXPECT)) == 8


def test_group_describe_parses_lag_members_and_topics() -> None:
    text = (
        "GROUP                  lt-flash\nSTATE                  Stable\nMEMBERS                1\n"
        "TOTAL-LAG              7\n\n"
        "TOPIC  PARTITION  CURRENT-OFFSET  LOG-START-OFFSET  LOG-END-OFFSET  LAG  MEMBER-ID\n"
        "lt-rag-responses  0  480  0  487  7  aio-1\n"
    )
    assert parse_group_describe(text) == {
        "state": "Stable",
        "members": 1,
        "total_lag": 7,
        "topics": ["lt-rag-responses"],
    }
    assert parse_group_describe("")["total_lag"] is None


def test_reconcile_names_every_gap_between_adjacent_legs() -> None:
    # a, b, c answered 200 with ids. d was blocked and e timed out, so neither has an id.
    responses: list[tuple[str | None, int | None]] = [
        ("a", 200),
        ("b", 200),
        ("c", 200),
        (None, 403),
        (None, None),
    ]
    events = {"a": 1, "b": 2, "x": 1, "y": 1}  # c has no event, b is duplicated, x and y have no id
    result = reconcile(responses, events, ["a", "b"], {"a": 1}, ["a"])
    assert result["sent_requests"] == 5 and result["http_responses"] == 4
    assert result["responses_with_trace_id"] == 3 and result["requests_without_trace_id"] == 2
    assert result["response_id_without_event"] == 1  # c
    assert result["response_id_without_event_examples"] == ["c"]
    assert result["events_unmatched_to_a_response_id"] == 2  # x, y
    assert result["unmatched_events_minus_requests_without_id"] == 0  # the two id-less requests
    assert result["duplicate_events"] == 1
    assert result["event_without_verdict"] == 2  # x, y
    assert result["topic_event_not_persisted"] == 3  # b, x, y
    assert result["verdict_not_persisted"] == 1  # b


def test_span_stats_groups_by_name_and_respects_the_stage_window(tmp_path: Path) -> None:
    rows = [
        {"n": "rag.input_rails", "ms": 100.0, "t": 10.0},
        {"n": "rag.input_rails", "ms": 300.0, "t": 11.0},
        {"n": "rag.input_rails", "ms": 9999.0, "t": 50.0},  # outside the window
        {"n": "rag.vector_search", "ms": 20.0, "t": 10.5},
    ]
    path = tmp_path / "spans.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    stats = span_stats(path, 9.0, 12.0)
    assert stats["rag.input_rails"] == {
        "count": 2,
        "p50_ms": 100.0,
        "p95_ms": 300.0,
        "mean_ms": 200.0,
    }
    assert stats["rag.vector_search"]["count"] == 1
