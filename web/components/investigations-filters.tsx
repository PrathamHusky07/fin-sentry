export interface InvestigationsFilterState {
  q: string;
  ticker: string;
  ragStatus: string;
  judgeState: string;
  frontierSampled: string;
  disagreement: boolean;
}

export const EMPTY_FILTERS: InvestigationsFilterState = {
  q: "",
  ticker: "",
  ragStatus: "",
  judgeState: "",
  frontierSampled: "",
  disagreement: false,
};

const RAG_STATUS_OPTIONS = [
  { value: "success", label: "Delivered" },
  { value: "blocked", label: "Blocked" },
  { value: "error", label: "Error" },
] as const;

const JUDGE_STATE_OPTIONS = [
  { value: "evaluated", label: "Evaluated" },
  { value: "partially_evaluated", label: "Partially evaluated" },
  { value: "blocked_before_evaluation", label: "Blocked before evaluation" },
  { value: "judge_failed", label: "Judge pipeline error" },
  { value: "never_evaluated", label: "Not yet evaluated" },
] as const;

const CONTROL =
  "border-border-strong bg-background-elevated text-text-primary hover:border-text-tertiary min-h-11 rounded-lg border px-3 text-sm transition-colors";

const SELECT = `${CONTROL} min-w-0 flex-1 basis-40 sm:flex-none sm:basis-auto`;

export function hasActiveFilters(f: InvestigationsFilterState): boolean {
  return (
    f.q !== "" ||
    f.ticker !== "" ||
    f.ragStatus !== "" ||
    f.judgeState !== "" ||
    f.frontierSampled !== "" ||
    f.disagreement
  );
}

const OUTCOMES = [{ value: "", label: "All" }, ...RAG_STATUS_OPTIONS] as const;

/**
 * Two tiers. The search box is the primary control and spans the row. Under
 * it, the outcome switch and the flash/frontier disagreement lens, the two
 * questions an investigator asks first, sit on the left, and the narrower
 * filters sit on the right.
 */
export function InvestigationsFilters({
  filters,
  onChange,
}: {
  filters: InvestigationsFilterState;
  onChange: (next: InvestigationsFilterState) => void;
}) {
  return (
    <div role="search" className="space-y-3">
      <div className="relative">
        <svg
          viewBox="0 0 20 20"
          className="text-text-tertiary pointer-events-none absolute top-1/2 left-4 h-4 w-4 -translate-y-1/2"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          aria-hidden="true"
        >
          <circle cx="9" cy="9" r="5.5" />
          <path d="M13.5 13.5L17 17" strokeLinecap="round" />
        </svg>
        <input
          type="search"
          value={filters.q}
          onChange={(e) => onChange({ ...filters, q: e.target.value })}
          placeholder="Search query text or trace ID…"
          aria-label="Search query text or trace ID"
          autoComplete="off"
          className={`${CONTROL} min-h-12 w-full pl-11 text-base`}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div
            role="group"
            aria-label="Filter by outcome"
            className="border-border-strong bg-background-elevated inline-flex rounded-lg border p-0.5"
          >
            {OUTCOMES.map((o) => (
              <button
                key={o.value}
                type="button"
                aria-pressed={filters.ragStatus === o.value}
                onClick={() => onChange({ ...filters, ragStatus: o.value })}
                className={`min-h-10 rounded-md px-3.5 text-sm transition-colors ${
                  filters.ragStatus === o.value
                    ? "bg-surface-high text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            aria-pressed={filters.disagreement}
            onClick={() =>
              onChange({ ...filters, disagreement: !filters.disagreement })
            }
            className={`min-h-11 rounded-lg border px-3.5 text-sm font-medium transition-colors ${
              filters.disagreement
                ? "border-disagreement bg-disagreement/10 text-disagreement"
                : "border-border-strong text-text-secondary hover:border-disagreement/60 hover:text-disagreement"
            }`}
          >
            Flash/frontier disagreement
          </button>
        </div>

        <div className="flex flex-1 flex-wrap items-center gap-2 sm:flex-none">
          <input
            type="text"
            value={filters.ticker}
            onChange={(e) => onChange({ ...filters, ticker: e.target.value })}
            placeholder="Ticker…"
            aria-label="Filter by ticker"
            autoComplete="off"
            spellCheck={false}
            className={`${CONTROL} w-24 font-mono uppercase placeholder:normal-case`}
          />
          <select
            value={filters.judgeState}
            onChange={(e) =>
              onChange({ ...filters, judgeState: e.target.value })
            }
            aria-label="Filter by judge state"
            className={SELECT}
          >
            <option value="">All judge states</option>
            {JUDGE_STATE_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <select
            value={filters.frontierSampled}
            onChange={(e) =>
              onChange({ ...filters, frontierSampled: e.target.value })
            }
            aria-label="Filter by frontier sampling"
            className={SELECT}
          >
            <option value="">Sampled or not</option>
            <option value="true">Frontier sampled</option>
            <option value="false">Not sampled</option>
          </select>
        </div>
      </div>
    </div>
  );
}
