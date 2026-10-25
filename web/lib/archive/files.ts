import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";

/**
 * Reads the committed archive files that archived-evidence mode serves. Each path is a literal
 * at its call site so Next's file tracing, and the explicit includes in next.config.ts, name the
 * same few files. The files are immutable at runtime, so each is read and parsed once per
 * server instance and shared by every request.
 *
 * A file that is missing or malformed throws ArchiveUnavailableError. The route answers 503,
 * which the pages already show as unavailable. Nothing is filled in.
 */
export class ArchiveUnavailableError extends Error {}

function memo<T>(load: () => Promise<T>): () => Promise<T> {
  let cached: Promise<T> | undefined;
  return () => {
    cached ??= load().catch((error: unknown) => {
      cached = undefined;
      throw error;
    });
    return cached;
  };
}

async function readText(file: string): Promise<string> {
  try {
    return await readFile(file, "utf-8");
  } catch {
    throw new ArchiveUnavailableError(`archive file not readable`);
  }
}

export function parseJsonl(text: string): unknown[] {
  try {
    return text
      .split("\n")
      .filter((line) => line.trim() !== "")
      .map((line) => JSON.parse(line) as unknown);
  } catch {
    throw new ArchiveUnavailableError("archive file is not valid JSON lines");
  }
}

export type JsonObject = Record<string, unknown>;

export function asObject(value: unknown): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ArchiveUnavailableError("archive record is not an object");
  }
  return value as JsonObject;
}

export function str(o: JsonObject, key: string): string {
  const v = o[key];
  if (typeof v !== "string") {
    throw new ArchiveUnavailableError(`archive field ${key} is not a string`);
  }
  return v;
}

export function strOrNull(o: JsonObject, key: string): string | null {
  const v = o[key];
  if (v === null || v === undefined) return null;
  if (typeof v !== "string") {
    throw new ArchiveUnavailableError(`archive field ${key} is not a string`);
  }
  return v;
}

export function numOrNull(o: JsonObject, key: string): number | null {
  const v = o[key];
  if (v === null || v === undefined) return null;
  if (typeof v !== "number") {
    throw new ArchiveUnavailableError(`archive field ${key} is not a number`);
  }
  return v;
}

export function num(o: JsonObject, key: string): number {
  const v = numOrNull(o, key);
  if (v === null) {
    throw new ArchiveUnavailableError(`archive field ${key} is missing`);
  }
  return v;
}

export function bool(o: JsonObject, key: string): boolean {
  const v = o[key];
  if (typeof v !== "boolean") {
    throw new ArchiveUnavailableError(`archive field ${key} is not a boolean`);
  }
  return v;
}

/** One stream record: the archive keeps the Kafka offset beside the event value. */
export interface StreamRecord {
  offset: number;
  value: JsonObject;
}

function streamRecords(text: string): StreamRecord[] {
  return parseJsonl(text).map((raw) => {
    const r = asObject(raw);
    return { offset: num(r, "offset"), value: asObject(r["value"]) };
  });
}

function rows(text: string): JsonObject[] {
  return parseJsonl(text).map(asObject);
}

export const ragResponses = memo(async () =>
  streamRecords(
    await readText(
      path.join(
        process.cwd(),
        "..",
        "docs",
        "demo-archive",
        "stream",
        "rag-responses.jsonl",
      ),
    ),
  ),
);

export const judgeVerdicts = memo(async () =>
  streamRecords(
    await readText(
      path.join(
        process.cwd(),
        "..",
        "docs",
        "demo-archive",
        "stream",
        "judge-verdicts.jsonl",
      ),
    ),
  ),
);

export const frontierVerdicts = memo(async () =>
  streamRecords(
    await readText(
      path.join(
        process.cwd(),
        "..",
        "docs",
        "demo-archive",
        "stream",
        "rag-frontier-verdicts.jsonl",
      ),
    ),
  ),
);

export const redTeamRuns = memo(async () =>
  rows(
    await readText(
      path.join(
        process.cwd(),
        "..",
        "docs",
        "demo-archive",
        "postgres",
        "red_team_runs.jsonl",
      ),
    ),
  ),
);

export const redTeamExecutions = memo(async () =>
  rows(
    await readText(
      path.join(
        process.cwd(),
        "..",
        "docs",
        "demo-archive",
        "postgres",
        "red_team_executions.jsonl",
      ),
    ),
  ),
);

export const investigations = memo(async () =>
  rows(
    await readText(
      path.join(
        process.cwd(),
        "..",
        "docs",
        "demo-archive",
        "postgres",
        "investigations.jsonl",
      ),
    ),
  ),
);

export const investigationEvents = memo(async () =>
  rows(
    await readText(
      path.join(
        process.cwd(),
        "..",
        "docs",
        "demo-archive",
        "postgres",
        "investigation_events.jsonl",
      ),
    ),
  ),
);

/** The recorded gateway round-trip probe runs. The manifest pins this file as a committed
 * reference, and a restore skips it. */
export const gatewayProbeRuns = memo(async () =>
  rows(
    await readText(
      path.join(
        process.cwd(),
        "..",
        "docs",
        "demo-archive",
        "postgres",
        "gateway_probe_runs.jsonl",
      ),
    ),
  ),
);

/** The Red Team scenario registry, the committed reference the archive manifest pins. */
export const scenariosYaml = memo(() =>
  readText(
    path.join(process.cwd(), "..", "finsentry", "redteam", "scenarios.yml"),
  ),
);

/** The canary artifact the calibration reading is taken from. */
export const canarySmoke = memo(async () => {
  const text = await readText(
    path.join(
      process.cwd(),
      "..",
      "docs",
      "measurements",
      "reliability",
      "canary-live-smoke-d6p2.json",
    ),
  );
  try {
    return asObject(JSON.parse(text) as unknown);
  } catch {
    throw new ArchiveUnavailableError("canary artifact is not valid JSON");
  }
});
