import Link from "next/link";
import { Panel } from "@/components/panel";
import { StatusDot } from "@/components/status-dot";
import type { BlockReasonCount } from "@/lib/overview-data";
import type { CalibrationHealthResponse, TraceListItem } from "@/lib/trace-api";

interface AttentionItem {
  key: string;
  color: "warning" | "failure" | "info" | "disagreement";
  text: string;
  href: string;
}

// Day 9 Session 2B: malformed_json and schema_violation are two distinct
// real block reasons (unparseable JSON vs. valid JSON in the wrong shape --
// see docs/internal/day9-frontend-data-contract.md's Contract v2). They
// used to collapse to the same "schema violation" label before
// schema_violation existed as its own reason; kept distinct here so the
// breakdown never shows two different-looking entries that are actually
// the same mapped label.
const BLOCK_REASON_LABEL: Record<string, string> = {
  input_rail_blocked: "prompt injection (input rail)",
  no_trustworthy_sources: "untrusted retrieval source",
  malformed_json: "malformed JSON",
  schema_violation: "schema violation (valid JSON, wrong shape)",
  hallucinated_citation: "hallucinated citation",
  low_faithfulness: "low faithfulness",
};

function formatBlockReason(reason: string): string {
  return BLOCK_REASON_LABEL[reason] ?? reason;
}

/**
 * Real conditions only -- every item here traces to a persisted field or a
 * documented derivation (see ../lib/overview-data.ts and the data
 * contract). An empty list renders an honest "nothing needs attention"
 * state, never a fabricated all-clear metric.
 */
export function AttentionRequired({
  calibration,
  disagreementTraces,
  blockedTotal,
  blockedByReason,
}: {
  calibration: CalibrationHealthResponse | null;
  disagreementTraces: TraceListItem[];
  blockedTotal: number;
  blockedByReason: BlockReasonCount[];
}) {
  const items: AttentionItem[] = [];

  if (calibration && calibration.position !== "at_or_above_recovery") {
    const kappaText =
      calibration.kappa !== null ? calibration.kappa.toFixed(3) : "unavailable";
    items.push({
      key: "calibration",
      color:
        calibration.position === "at_or_below_entry" ? "failure" : "warning",
      text: `Calibration ${calibration.state ?? "degraded"} -- κ ${kappaText} vs. recovery threshold ${calibration.recovery_threshold.toFixed(2)}`,
      href: "/operations",
    });
  }

  if (disagreementTraces.length > 0) {
    items.push({
      key: "disagreement",
      color: "disagreement",
      text: `Flash/frontier disagreement: ${disagreementTraces.length} trace${disagreementTraces.length === 1 ? "" : "s"} where the frontier judge contradicted the flash tier`,
      href: "/investigations?disagreement=true",
    });
  }

  if (blockedTotal > 0) {
    const breakdown = blockedByReason
      .map((r) => `${r.count} ${formatBlockReason(r.reason)}`)
      .join(", ");
    items.push({
      key: "blocked",
      color: "info",
      text: `Blocked requests: ${blockedTotal} (${breakdown})`,
      href: "/investigations?status=blocked",
    });
  }

  return (
    <Panel className="p-4">
      <h2 className="text-text-primary text-sm font-semibold">
        Attention required
      </h2>
      {items.length === 0 ? (
        <p className="text-text-secondary mt-3 text-sm">
          No real conditions currently need attention.
        </p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {items.map((item) => (
            <li key={item.key}>
              <Link
                href={item.href}
                className="hover:bg-surface focus-visible:outline-accent flex items-start gap-2.5 rounded-md p-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2"
              >
                <span className="mt-1.5">
                  <StatusDot color={item.color} />
                </span>
                <span className="text-text-primary">{item.text}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
