# Demo archive

A versioned copy of the records the demo depends on, taken from where they are actually stored.
`manifest.json` lists every file with its record count, size, sha256 and a digest of its ids.

| Dataset | Where it lives | Archive file |
|---|---|---|
| Flash and frontier judge inputs and outputs | Redpanda topics `rag-responses`, `judge-verdicts`, `rag-frontier-verdicts` (RisingWave only reads them) | `stream/*.jsonl` |
| Red Team runs and executions | Postgres tables, already durable | `postgres/red_team_*.jsonl` |
| Agent investigations and events | Postgres tables, already durable | `postgres/investigation*.jsonl` |
| Gateway round-trip probe | Postgres table `gateway_probe_runs`, one recorded run | `postgres/gateway_probe_runs.jsonl` |

The probe file is telemetry for the archived-evidence site. The manifest pins it as a committed reference with its sha256 and it is not a dataset, so `materialize` and `recover` skip it. A restore would write id 1 without advancing the table's sequence, and the next probe run would collide with it.

Only the three topics were stream-only, so only they also have a Postgres table (`stream_archive`, migration 008).
The Red Team and Agent tables are not copied into a second table. The archive is their off-machine copy.

## Commands

Run from the project root. All of them are read only except `materialize` and `republish`.

```
python -m finsentry.archive export       # merge the live data into docs/demo-archive, never dropping a record
python -m finsentry.archive verify       # checksums, counts and ids, with no network
python -m finsentry.archive reconcile    # archive against the live topics, RisingWave and Postgres
python -m finsentry.archive materialize  # load into Postgres, idempotent, never overwrites a row
python -m finsentry.archive republish --topic judge-verdicts --into <topic>
python -m finsentry.archive coverage     # which demo questions have a complete stored execution
python -m finsentry.archive recover      # rehearse the full restore in disposable databases
```

## Recovering the demo without rerunning RAG

Run the order below on a machine that has the repository, Docker and nothing else. No step asks the gateway a
question or calls Gemini.

1. `docker compose -f docker-compose.dev.yml up -d postgres redpanda risingwave` starts the three stores.
   Do not start the dashboard, the gateway or any `finsentry.consumer` process yet.
2. `python -m finsentry.db.migrate` creates the tables, `stream_archive` included.
3. `python -m finsentry.archive verify` checks the files against the manifest with no network.
4. `python -m finsentry.archive materialize` restores the Red Team and Agent rows and fills `stream_archive`.
   It is idempotent and never overwrites a row that already exists.
5. `python scripts/init_risingwave.py` creates the three topics (one partition each), the RisingWave sources
   and the eight views. `python scripts/demo_seed.py retention` then sets `retention.ms=-1` on the topics.
6. `python -m finsentry.archive republish --topic <name> --into <name> --allow-live`, once per topic. The
   flag is required because these are the live topic names. The command refuses to run while any
   `finsentry.consumer` process exists. That refusal keeps a replay from running 325 Gemini evaluations,
   because the flash consumer judges every event it reads from `rag-responses`. RisingWave reads the
   topics from the earliest offset, so the views rebuild by themselves.
7. `python -m finsentry.archive reconcile` compares the archive with the topics, RisingWave and Postgres.
8. Start the dashboard, then the gateway, then the web app. Start the consumers last, and only if new
   traffic is wanted. On a clean machine a consumer group has no committed offset and reads from the end
   of the topic (the aiokafka default), so it does not judge the replay. On a machine where the group
   already has committed offsets below the replay, a consumer would judge every replayed event, so
   do not start it there.

## Rehearsing the recovery

`python -m finsentry.archive recover` runs the whole restore against disposable copies and prints one
PASS or FAIL line per check. It creates a Postgres database and a RisingWave database named
`finsentry_recovery_<token>` and three replay topics named `recovery-<token>-<topic>`. It does not connect to
the development database, does not write to a live topic and does not change the archive. It drops
everything it created, including when a check fails.

It checks that:

- the restore inserts the manifest's counts, and every restored row is byte-identical to its archived line;
- the two foreign keys exist and nothing is orphaned;
- every flash and frontier verdict has its request in the archive;
- a second restore adds nothing and a restore never overwrites an edited row;
- `init.sql` rebuilds the eight views, each source holds every archived record and the request view counts
  every archived request;
- the dashboard's trace routes return an archived delivered answer with its citations and an archived
  block with its rail, read from the rebuilt views;
- the Red Team and Agent routers return all 27 runs, 43 executions with evidence, 7 investigations and 39
  timeline events, and no planner or tool session was opened.

The replay topics have names no consumer subscribes to, so the rehearsal makes no Gemini call. The pytest
version, `tests/archive/test_recovery.py`, also asserts that the development row counts and the live topic
end offsets are the same before and after.

## What guarantees durability, and what does not

- Retention alone is not durability. Setting `retention.ms=-1` keeps the topics on one Docker volume on one machine.
- The git copy of this directory is the off-machine copy, and it exists only once it is pushed.
- Records are content addressed, so loading the same archive twice adds nothing.
- Postgres is durable only as long as its Docker volume is.

## What the archive omits

The manifest lists it. The corpus, golden set and hallucination benchmark tables are reproducible from public
sources. RisingWave views are derived. A replay assigns new Kafka offsets, and each record keeps its original
offset and timestamp as data. The original Amazon disagreement trace is not here because its records had already
expired from the topics. Its recovered fields are in `docs/demo-seed/amzn-disagreement-v1.json`.
