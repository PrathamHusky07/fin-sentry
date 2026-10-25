"""
The demo archive's file format, and the checks that read it back without touching a
network, a broker or a database.

An archive is a directory of JSONL files plus manifest.json. Every file is listed in the
manifest with its record count, byte size, sha256 and a digest of the natural ids it holds.
Stream records (one line per Kafka record) carry a content id, the sha256 of the record's
canonical JSON value, so the same event is the same record wherever it is replayed. Table
rows are the text Postgres itself produces for `to_jsonb(row)`, written unchanged, so the
same rows always produce the same bytes and the same checksum.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

SCHEMA_VERSION = 1
MANIFEST = "manifest.json"

# A table dataset's natural id: the columns that identify one row.
TABLE_ID_COLUMNS: dict[str, tuple[str, ...]] = {
    "red_team_runs": ("run_id",),
    "red_team_executions": ("execution_id",),
    "investigations": ("investigation_id",),
    "investigation_events": ("investigation_id", "seq"),
    # Exported for the archived-evidence site only. It is not in TABLE_ORDER, so a restore skips it.
    "gateway_probe_runs": ("id",),
}


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ids_digest(ids: Iterable[str]) -> str:
    return sha256_text("\n".join(sorted(ids)))


def stream_line(offset: int, timestamp_ms: int, key: str | None, value: object) -> str:
    """One Kafka record as one JSONL line. `id` is the content id of the value."""
    return canonical(
        {
            "id": sha256_text(canonical(value)),
            "offset": offset,
            "timestamp_ms": timestamp_ms,
            "key": key,
            "value": value,
        }
    )


def row_id(table: str, row: dict[str, object]) -> str:
    return ":".join(str(row[c]) for c in TABLE_ID_COLUMNS[table])


def file_entry(
    directory: Path, rel: str, kind: str, ids: list[str], source: dict[str, object]
) -> dict[str, object]:
    data = (directory / rel).read_bytes()
    return {
        "path": rel,
        "kind": kind,
        "records": len(ids),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "ids_sha256": ids_digest(ids),
        "source": source,
    }


def read_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def dataset_ids(name: str, kind: str, rows: list[dict[str, object]]) -> list[str]:
    if kind == "stream":
        return [str(r["id"]) for r in rows]
    return [row_id(name, r) for r in rows]


def verify_archive(directory: Path) -> list[str]:
    """Every problem found reading the archive back, or an empty list. Checks the manifest's
    schema version, each file's checksum, size and record count, each stream record's
    content id against its value, and each file's id digest."""
    manifest_path = directory / MANIFEST
    if not manifest_path.is_file():
        return [f"{MANIFEST} is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version is {manifest.get('schema_version')!r}, not {SCHEMA_VERSION}"
        )
    for name, entry in manifest.get("datasets", {}).items():
        path = directory / entry["path"]
        if not path.is_file():
            problems.append(f"{name}: {entry['path']} is missing")
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            problems.append(f"{name}: sha256 does not match the manifest")
        if len(data) != entry["bytes"]:
            problems.append(f"{name}: {len(data)} bytes, manifest says {entry['bytes']}")
        rows = read_lines(path)
        if len(rows) != entry["records"]:
            problems.append(f"{name}: {len(rows)} records, manifest says {entry['records']}")
        if entry["kind"] == "stream":
            bad = [r["offset"] for r in rows if r["id"] != sha256_text(canonical(r["value"]))]
            if bad:
                problems.append(f"{name}: content id does not match the value at offsets {bad[:5]}")
        if ids_digest(dataset_ids(name, entry["kind"], rows)) != entry["ids_sha256"]:
            problems.append(f"{name}: the set of ids does not match the manifest")
    return problems
