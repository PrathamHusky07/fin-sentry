"use client";

import { useState } from "react";
import { Section } from "@/components/trace-sections";
import type { TraceDetailResponse } from "@/lib/trace-api";

/** What the answer and the frontier judge each did with one chunk, in words.
 * Built only from persisted fields: the citation list and the frontier
 * evidence's supporting and contradicting chunk ids. */
function chunkMeaning(
  detail: TraceDetailResponse,
  id: string,
  cited: boolean,
): string {
  const evidence = detail.frontier.evidence;
  const parts = [cited ? "Cited by the answer." : "Not cited by the answer."];
  if (evidence) {
    if (evidence.cited_chunks_supporting.includes(id)) {
      parts.push("The frontier judge found it supporting.");
    } else if (evidence.cited_chunks_contradicting.includes(id)) {
      parts.push("The frontier judge found it contradicting.");
    } else {
      parts.push("The frontier judge did not name it.");
    }
  }
  return parts.join(" ");
}

/** The retrieved chunks and what the answer made of them. A chunk is marked
 * cited when the answer cites it, and marked again when the frontier judge
 * named it as supporting or contradicting. Pointing at a chunk says what
 * each party did with it and lights the quotes the answer drew from it. */
export function Evidence({ detail }: { detail: TraceDetailResponse }) {
  const [active, setActive] = useState<string | null>(null);
  const cited = new Set(detail.citations.map((c) => c.chunk_id));
  const supporting = new Set(
    detail.frontier.evidence?.cited_chunks_supporting ?? [],
  );
  const contradicting = new Set(
    detail.frontier.evidence?.cited_chunks_contradicting ?? [],
  );
  const stoppedBefore = detail.rag_status !== "success";
  const retrieved = detail.retrieved_chunk_ids.length;
  const citedCount = cited.size;

  return (
    <Section title="Evidence the answer rests on" id="trace-evidence">
      <p className="text-text-secondary text-base">
        {retrieved} chunk{retrieved === 1 ? "" : "s"} retrieved, {citedCount}{" "}
        cited in the answer.
        {retrieved > 0 && citedCount === 0 && !stoppedBefore
          ? " The model cited none of the retrieved context."
          : ""}
      </p>
      {retrieved > 0 ? (
        <>
          <ul className="mt-3 flex flex-wrap gap-2">
            {detail.retrieved_chunk_ids.map((id) => {
              const tags = [
                cited.has(id) ? "cited" : "not cited",
                supporting.has(id) ? "frontier: supports" : null,
                contradicting.has(id) ? "frontier: contradicts" : null,
              ].filter((t): t is string => t !== null);
              const isActive = active === id;
              return (
                <li key={id}>
                  <button
                    type="button"
                    aria-label={`${id}. ${chunkMeaning(detail, id, cited.has(id))}`}
                    onPointerEnter={(e) => {
                      if (e.pointerType === "mouse") setActive(id);
                    }}
                    onPointerLeave={(e) => {
                      if (e.pointerType === "mouse") setActive(null);
                    }}
                    onFocus={() => setActive(id)}
                    onBlur={() => setActive(null)}
                    onClick={() => setActive((a) => (a === id ? null : id))}
                    className={`min-h-11 rounded-md border px-2.5 py-1 text-left transition-[background-color,border-color,opacity] duration-[var(--dur-base)] ease-[var(--ease-soft)] ${
                      cited.has(id)
                        ? "border-accent/50 bg-accent/5"
                        : "border-border-strong"
                    } ${isActive ? "bg-surface-hover border-line-active" : ""} ${active !== null && !isActive ? "opacity-50" : ""}`}
                  >
                    <span
                      className={`font-mono text-xs ${cited.has(id) ? "text-accent" : "text-text-tertiary"}`}
                    >
                      {id}
                    </span>
                    <span
                      className={`ml-2 text-xs ${contradicting.has(id) ? "text-disagreement" : "text-text-tertiary"}`}
                    >
                      {tags.join(", ")}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          <p
            aria-live="polite"
            className="text-text-tertiary mt-2 min-h-6 text-sm"
          >
            {active
              ? chunkMeaning(detail, active, cited.has(active))
              : "Point at a chunk to see how the answer and the frontier judge used it."}
          </p>
        </>
      ) : (
        <p className="text-text-tertiary mt-2 text-sm">
          No retrieved chunk ids were recorded for this trace.
        </p>
      )}
      {detail.citations.length > 0 ? (
        <ul className="mt-5 space-y-4">
          {detail.citations.map((c, index) => (
            <li
              key={`${c.chunk_id}-${index}`}
              className={`border-l-2 pl-4 transition-[opacity,border-color] duration-[var(--dur-base)] ease-[var(--ease-soft)] ${
                active === c.chunk_id
                  ? "border-accent"
                  : active !== null
                    ? "border-accent/20 opacity-45"
                    : "border-accent/40"
              }`}
            >
              <span className="text-accent font-mono text-xs">
                {c.chunk_id}
              </span>
              <p className="text-text-primary mt-1 text-base leading-relaxed">
                {c.quote}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}
