"""web/lib/demo-record.json names the demonstration records. This checks the file against the
committed archive, so it can never point at a record the archive does not hold."""

from __future__ import annotations

import json
from pathlib import Path

from finsentry.archive.export import DEFAULT_DIR
from finsentry.archive.format import read_lines

_RECORD = Path(__file__).resolve().parents[2] / "web" / "lib" / "demo-record.json"


def test_the_reasked_amazon_trace_is_archived_with_its_complete_flash_verdict() -> None:
    record = json.loads(_RECORD.read_text())
    trace = record["reask"]["app_trace_id"]
    assert trace != record["disagreement"]["app_trace_id"], "the new trace is not the original"

    events = [
        r["value"]
        for r in read_lines(DEFAULT_DIR / "stream" / "rag-responses.jsonl")
        if r["value"]["app_trace_id"] == trace
    ]
    assert len(events) == 1
    event = events[0]
    assert event["status"] == "success" and event["answer"] and event["retrieved_chunk_ids"]
    assert "net income attributable to shareholders" in event["query"]

    flash = [
        r["value"]
        for r in read_lines(DEFAULT_DIR / "stream" / "judge-verdicts.jsonl")
        if r["value"]["app_trace_id"] == trace
    ]
    assert [v["status"] for v in flash] == ["complete"]
    frontier = [
        r
        for r in read_lines(DEFAULT_DIR / "stream" / "rag-frontier-verdicts.jsonl")
        if r["value"]["app_trace_id"] == trace
    ]
    assert frontier == [] and record["reask"]["frontier_sampled"] is False


def test_a_historical_disagreement_names_a_capture_file_that_exists() -> None:
    record = json.loads(_RECORD.read_text())["disagreement"]
    assert record["origin"] in {"historical", "live"}
    if record["origin"] == "historical":
        capture = _RECORD.parents[2] / record["capture"]
        assert json.loads(capture.read_text())["app_trace_id"] == record["app_trace_id"]
