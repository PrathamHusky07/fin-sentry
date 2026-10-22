"""The archive format: what verification catches, and that the committed archive passes it."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from finsentry.archive.export import DEFAULT_DIR, OMITTED, _merge
from finsentry.archive.format import (
    MANIFEST,
    SCHEMA_VERSION,
    canonical,
    file_entry,
    ids_digest,
    sha256_text,
    stream_line,
    verify_archive,
)


def _tiny_archive(tmp_path: Path) -> Path:
    """A real two-dataset archive built with the production writers, so every check below
    mutates something that passed before it was touched."""
    d = tmp_path / "archive"
    (d / "stream").mkdir(parents=True)
    (d / "postgres").mkdir()
    lines = [
        stream_line(10, 1_700_000_000_000, None, {"event_id": "e1", "n": 1}),
        stream_line(11, 1_700_000_001_000, "k", {"event_id": "e2", "n": 2}),
    ]
    (d / "stream" / "rag-responses.jsonl").write_text("".join(f"{x}\n" for x in lines))
    runs = ['{"run_id": "r1", "status": "completed"}']
    (d / "postgres" / "red_team_runs.jsonl").write_text("".join(f"{x}\n" for x in runs))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "datasets": {
            "rag-responses": file_entry(
                d,
                "stream/rag-responses.jsonl",
                "stream",
                [json.loads(x)["id"] for x in lines],
                {"topic": "rag-responses"},
            ),
            "red_team_runs": file_entry(
                d, "postgres/red_team_runs.jsonl", "table", ["r1"], {"table": "red_team_runs"}
            ),
        },
        "omitted": OMITTED,
    }
    (d / MANIFEST).write_text(json.dumps(manifest))
    return d


def test_a_well_formed_archive_verifies(tmp_path: Path) -> None:
    assert verify_archive(_tiny_archive(tmp_path)) == []


def test_a_changed_byte_is_caught_by_the_checksum(tmp_path: Path) -> None:
    d = _tiny_archive(tmp_path)
    path = d / "postgres" / "red_team_runs.jsonl"
    path.write_text(path.read_text().replace("completed", "completer"))
    problems = verify_archive(d)
    assert any("red_team_runs: sha256 does not match" in p for p in problems)


def test_a_dropped_record_is_caught_by_count_and_ids(tmp_path: Path) -> None:
    d = _tiny_archive(tmp_path)
    path = d / "stream" / "rag-responses.jsonl"
    first = path.read_text().splitlines()[0]
    path.write_text(first + "\n")
    problems = verify_archive(d)
    assert any("1 records, manifest says 2" in p for p in problems)
    assert any("the set of ids does not match" in p for p in problems)


def test_a_record_whose_value_was_edited_fails_its_content_id(tmp_path: Path) -> None:
    d = _tiny_archive(tmp_path)
    path = d / "stream" / "rag-responses.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    rows[0]["value"]["n"] = 99
    path.write_text("".join(canonical(r) + "\n" for r in rows))
    manifest = json.loads((d / MANIFEST).read_text())
    manifest["datasets"]["rag-responses"] = file_entry(
        d, "stream/rag-responses.jsonl", "stream", [r["id"] for r in rows], {}
    )
    (d / MANIFEST).write_text(json.dumps(manifest))
    # The file now matches the manifest, so only the content id can notice the edit.
    problems = verify_archive(d)
    assert problems and "content id does not match the value" in problems[0]


def test_a_missing_file_a_missing_manifest_and_a_wrong_schema_version_are_reported(
    tmp_path: Path,
) -> None:
    d = _tiny_archive(tmp_path)
    (d / "postgres" / "red_team_runs.jsonl").unlink()
    assert any("red_team_runs.jsonl is missing" in p for p in verify_archive(d))
    manifest = json.loads((d / MANIFEST).read_text())
    manifest["schema_version"] = 99
    (d / MANIFEST).write_text(json.dumps(manifest))
    assert any("schema_version is 99" in p for p in verify_archive(d))
    (d / MANIFEST).unlink()
    assert verify_archive(d) == [f"{MANIFEST} is missing"]


def test_the_content_id_is_stable_across_key_order_and_whitespace() -> None:
    a = stream_line(1, 1, None, {"b": 1, "a": [1, 2]})
    b = stream_line(9, 2, "k", json.loads('{ "a": [1, 2],  "b": 1 }'))
    assert (
        json.loads(a)["id"] == json.loads(b)["id"] == sha256_text(canonical({"a": [1, 2], "b": 1}))
    )
    assert ids_digest(["b", "a"]) == ids_digest(["a", "b"])


def test_the_committed_archive_verifies_and_states_what_it_omits() -> None:
    assert verify_archive(DEFAULT_DIR) == []
    manifest = json.loads((DEFAULT_DIR / MANIFEST).read_text())
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert set(manifest["datasets"]) == {
        "rag-responses",
        "judge-verdicts",
        "rag-frontier-verdicts",
        "red_team_runs",
        "red_team_executions",
        "investigations",
        "investigation_events",
    }
    assert manifest["omitted"] == OMITTED and len(OMITTED) >= 4
    refs = {r["path"] for r in manifest["committed_references"]}
    assert "finsentry/redteam/scenarios.yml" in refs
    assert all(len(r["sha256"]) == 64 for r in manifest["committed_references"])


def test_merging_never_drops_an_archived_record_and_takes_the_current_row(tmp_path: Path) -> None:
    d = tmp_path
    (d / "stream").mkdir()
    old = [
        stream_line(1, 1000, None, {"event_id": "gone"}),
        stream_line(2, 2000, None, {"event_id": "kept"}),
    ]
    (d / "stream" / "t.jsonl").write_text("".join(f"{x}\n" for x in old))
    fresh = [old[1], stream_line(3, 3000, None, {"event_id": "new"})]
    merged = _merge(d, "stream/t.jsonl", "rag-responses", "stream", fresh)
    assert [json.loads(x)["value"]["event_id"] for x in merged] == ["gone", "kept", "new"]

    (d / "postgres").mkdir()
    (d / "postgres" / "red_team_runs.jsonl").write_text(
        '{"run_id": "a", "status": "running"}\n{"run_id": "deleted", "status": "completed"}\n'
    )
    rows = _merge(
        d,
        "postgres/red_team_runs.jsonl",
        "red_team_runs",
        "table",
        ['{"run_id": "a", "status": "completed"}'],
    )
    assert [json.loads(x)["run_id"] for x in rows] == ["a", "deleted"]
    assert json.loads(rows[0])["status"] == "completed"


def test_an_unchanged_export_would_write_identical_bytes(tmp_path: Path) -> None:
    d = _tiny_archive(tmp_path)
    copy = tmp_path / "copy"
    shutil.copytree(d, copy)
    fresh = (d / "postgres" / "red_team_runs.jsonl").read_text().splitlines()
    merged = _merge(copy, "postgres/red_team_runs.jsonl", "red_team_runs", "table", fresh)
    assert "".join(f"{x}\n" for x in merged) == (d / "postgres" / "red_team_runs.jsonl").read_text()


@pytest.mark.parametrize(
    "name", ["rag-responses.jsonl", "judge-verdicts.jsonl", "rag-frontier-verdicts.jsonl"]
)
def test_every_committed_stream_line_carries_its_original_offset_and_timestamp(name: str) -> None:
    lines = (DEFAULT_DIR / "stream" / name).read_text().splitlines()
    assert lines
    first = json.loads(lines[0])
    assert set(first) == {"id", "offset", "timestamp_ms", "key", "value"}
    assert isinstance(first["offset"], int) and first["timestamp_ms"] > 1_700_000_000_000


def test_a_first_write_is_ordered_like_every_later_merge(tmp_path: Path) -> None:
    rows = ['{"run_id": "b", "n": 1}', '{"run_id": "a", "n": 2}']
    first = _merge(tmp_path, "postgres/red_team_runs.jsonl", "red_team_runs", "table", rows)
    assert [json.loads(x)["run_id"] for x in first] == ["a", "b"]
