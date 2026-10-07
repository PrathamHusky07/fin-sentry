import { formatUtc, relativeTime } from "@/lib/format";
import {
  BLOCK_STAGE_LABEL,
  blockReasonLabel,
  blockReasonMeaning,
  blockStage,
} from "@/lib/labels";
import type { OverviewData } from "@/lib/overview-data";
import type {
  CalibrationHealthResponse,
  TraceDetailResponse,
} from "@/lib/trace-api";

export type AttentionTone = "failure" | "disagreement" | "warning" | "info";

export interface AttentionItem {
  key: string;
  tone: AttentionTone;
  title: string;
  /** The large figure that carries the signal, e.g. "6" or "κ 0.516". */
  figure: string;
  /** What the figure counts or compares, in plain words. */
  figureNote: string;
  /** What the data says, with the real numbers. */
  what: string;
  /** The technical reading for an engineer, shown last. */
  detail?: string;
  /** Why it matters for trusting the system. */
  why: string;
  href: string;
  cta: string;
}

const TONE_RANK: Record<AttentionTone, number> = {
  failure: 0,
  disagreement: 1,
  warning: 2,
  info: 3,
};

/** A block reason counts as a concentration when it accounts for at least
 * half of all blocks and there are enough blocks for that to mean anything.
 * A display rule for surfacing, not a classifier threshold. */
const CONCENTRATION_SHARE = 0.5;
const CONCENTRATION_MIN_BLOCKS = 5;

function plural(n: number, one: string, many: string = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * Every item below traces to a persisted field or a documented derivation.
 * An empty result means no rule fired, which the page states plainly. It is
 * never padded with a reassuring metric.
 */
export function buildAttentionItems({
  overview,
  calibration,
  disagreementDetails,
}: {
  overview: OverviewData | null;
  calibration: CalibrationHealthResponse | null;
  disagreementDetails: (TraceDetailResponse | null)[];
}): AttentionItem[] {
  const items: AttentionItem[] = [];

  if (overview && overview.errorCount > 0) {
    items.push({
      key: "errors",
      tone: "failure",
      title: `${plural(overview.errorCount, "request")} ended in an error`,
      figure: String(overview.errorCount),
      figureNote:
        overview.errorCount === 1 ? "request failed" : "requests failed",
      what: "These requests returned no answer because a dependency failed, so they were never evaluated. The trace detail names the cause.",
      why: "Errors show availability of the model path, not rail behavior. A rail cannot protect a request that never reached it.",
      href: "/investigations?status=error",
      cta: "Open errored executions",
    });
  }

  if (overview && overview.flow.deliveredJudgeFailed > 0) {
    items.push({
      key: "judge-failed",
      tone: "warning",
      title: `${plural(overview.flow.deliveredJudgeFailed, "delivered answer")} could not be judged`,
      figure: String(overview.flow.deliveredJudgeFailed),
      figureNote: "answers the judge could not score",
      what: "The request succeeded but the flash judge pipeline scored none of the three metrics.",
      why: "Quality for these answers is unmeasured, and the cause is the judge, not the answer.",
      href: "/investigations?judge_state=judge_failed",
      cta: "Open judge errors",
    });
  }

  if (!calibration) {
    items.push({
      key: "calibration-unavailable",
      tone: "warning",
      title: "Calibration unavailable",
      figure: "n/a",
      figureNote: "reading unavailable",
      what: "The calibration reading could not be loaded from the gateway, so the frontier judge’s agreement with labeled data is unknown right now.",
      why: "An unknown reading is not a healthy reading. Until it loads, the frontier judge’s verdicts are unverified.",
      href: "/operations#calibration",
      cta: "Open the calibration instrument",
    });
  }

  if (calibration && calibration.position !== "at_or_above_recovery") {
    const kappa =
      calibration.kappa !== null ? calibration.kappa.toFixed(3) : "unavailable";
    const asOf = calibration.state_as_of
      ? ` Manual reading, ${formatUtc(calibration.state_as_of)}, ${relativeTime(calibration.state_as_of)}.`
      : "";
    const below =
      calibration.position === "at_or_below_entry"
        ? `below the ${calibration.drift_entry_threshold.toFixed(2)} drift threshold`
        : calibration.position === "insufficient_data"
          ? "too few labeled rows to read"
          : `below the ${calibration.recovery_threshold.toFixed(2)} recovery threshold`;
    items.push({
      key: "calibration",
      tone:
        calibration.position === "at_or_below_entry"
          ? "failure"
          : calibration.position === "insufficient_data"
            ? "info"
            : "warning",
      title:
        calibration.position === "insufficient_data"
          ? "Frontier judge calibration has too little data"
          : calibration.position === "at_or_below_entry"
            ? "Frontier judge agreement is below the drift threshold"
            : "Frontier judge agreement needs attention",
      figure: kappa,
      figureNote: `Cohen’s kappa, ${below}`,
      what: "The frontier judge is the second opinion on a sample of answers. Its agreement with labeled financial examples is not at the level where it counts as recovered.",
      detail: `Cohen’s kappa ${kappa}${calibration.window_n !== null ? ` over ${calibration.window_n} labeled rows` : ""}. Drift starts at ${calibration.drift_entry_threshold.toFixed(2)}, recovery needs ${calibration.recovery_threshold.toFixed(2)}, healthy baseline ${calibration.healthy_baseline_kappa.toFixed(3)}. State: ${calibration.state ?? "unreported"}.${asOf}`,
      why: "This is one manual reading, not a live monitor. Until agreement recovers, treat the frontier judge’s verdicts as less certain.",
      href: "/operations#calibration",
      cta: "Open the calibration instrument",
    });
  }

  const disagreementCount = overview?.disagreementTraces.length ?? 0;
  if (overview && disagreementCount > 0) {
    overview.disagreementTraces.slice(0, 3).forEach((trace, i) => {
      const detail = disagreementDetails[i];
      const flash = detail?.flash?.faithfulness_score;
      const frontier = detail?.frontier.evidence?.faithfulness_score;
      const scores =
        flash != null && frontier != null
          ? `The flash judge scored faithfulness ${flash.toFixed(3)}. The frontier judge scored it ${frontier.toFixed(3)}.`
          : "The flash and frontier faithfulness scores differ by 0.5 or more.";
      items.push({
        key: `disagreement-${trace.app_trace_id}`,
        tone: "disagreement",
        title: `The two judge tiers disagree${trace.ticker ? ` on a ${trace.ticker} answer` : ""}`,
        figure:
          flash != null && frontier != null
            ? `${flash.toFixed(3)} vs ${frontier.toFixed(3)}`
            : "scores differ",
        figureNote: "flash against frontier faithfulness",
        what: `${scores} Question: ${trace.query}`,
        why: "The cheaper judge passed an answer the stronger judge rejected. Repeats of this would mean flash coverage overstates quality.",
        href: `/investigations?trace=${trace.app_trace_id}`,
        cta: "Open the trace",
      });
    });
    if (disagreementCount > 3) {
      items.push({
        key: "disagreement-more",
        tone: "disagreement",
        title: `${disagreementCount - 3} more cross-tier disagreements`,
        figure: String(disagreementCount - 3),
        figureNote: "more disagreements",
        what: "Only the three most recent are listed above.",
        why: "Each one is a delivered answer where the two judge tiers reached different verdicts.",
        href: "/investigations?disagreement=true",
        cta: "Open the disagreement lens",
      });
    }
  }

  if (overview && overview.flow.deliveredUnjudged > 0) {
    items.push({
      key: "unjudged",
      tone: "warning",
      title: `${plural(overview.flow.deliveredUnjudged, "delivered answer")} ${overview.flow.deliveredUnjudged === 1 ? "has" : "have"} no flash verdict`,
      figure: `${overview.flow.deliveredUnjudged} of ${overview.flow.delivered}`,
      figureNote: "delivered answers have no verdict",
      what: `The request succeeded but no verdict was persisted. That is ${overview.flow.deliveredUnjudged} of ${overview.flow.delivered} delivered answers.`,
      why: "Their quality is unmeasured. Evaluation runs off the request path, so this is a coverage gap in the evaluation plane, not a request failure.",
      href: "/investigations?judge_state=never_evaluated",
      cta: "Open unjudged executions",
    });
  }

  if (overview && overview.blockedTotal >= CONCENTRATION_MIN_BLOCKS) {
    const top = overview.blockedByReason[0];
    const share = top.count / overview.blockedTotal;
    if (share >= CONCENTRATION_SHARE) {
      const stage = BLOCK_STAGE_LABEL[blockStage(top.reason)].toLowerCase();
      items.push({
        key: "block-concentration",
        tone: "info",
        title: `Most blocked requests share one reason: ${blockReasonLabel(top.reason)}`,
        figure: `${top.count} of ${overview.blockedTotal}`,
        figureNote: `blocked at the ${stage}`,
        what: `${top.count} of ${overview.blockedTotal} blocked requests (${Math.round(share * 100)}%) were stopped at the ${stage}.`,
        why:
          (blockReasonMeaning(top.reason) ?? "") +
          " One dominant reason points to one cause to fix.",
        href: "/investigations?status=blocked",
        cta: "Open blocked executions",
      });
    }
  }

  return items.sort((a, b) => TONE_RANK[a.tone] - TONE_RANK[b.tone]);
}
