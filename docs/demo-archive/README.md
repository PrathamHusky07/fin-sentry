# Demo archive

A versioned copy of the records the demo depends on, taken from where they are actually stored.
`manifest.json` lists every file with its record count, size, sha256 and a digest of its ids.

| Dataset | Where it lives | Archive file |
|---|---|---|
| Flash and frontier judge inputs and outputs | Redpanda topics `rag-responses`, `judge-verdicts`, `rag-frontier-verdicts` (RisingWave only reads them) | `stream/*.jsonl` |
| Red Team runs and executions | Postgres tables, already durable | `postgres/red_team_*.jsonl` |
| Agent investigations and events | Postgres tables, already durable | `postgres/investigation*.jsonl` |

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
```

## Recovering the demo without rerunning RAG

1. `python -m finsentry.db.migrate` creates the tables.
2. `python -m finsentry.archive materialize` restores the Red Team and Agent rows and fills `stream_archive`.
3. To make the stream records visible to the pages again, `republish` each topic into a freshly created topic of
   the same name. Stop `finsentry.consumer.main` and the frontier consumer first. Every event on `rag-responses`
   makes the flash consumer call Gemini, and `republish` refuses a live topic while a consumer is running.

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
