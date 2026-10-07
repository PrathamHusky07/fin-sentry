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

export function InvestigationsFilters({
  filters,
  onChange,
}: {
  filters: InvestigationsFilterState;
  onChange: (next: InvestigationsFilterState) => void;
}) {
  return (
    <div role="search" className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-0 flex-1 basis-64">
        <svg
          viewBox="0 0 20 20"
          className="text-text-tertiary pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2"
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
          className={`${CONTROL} w-full pl-9`}
        />
      </div>
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
        value={filters.ragStatus}
        onChange={(e) => onChange({ ...filters, ragStatus: e.target.value })}
        aria-label="Filter by status"
        className={SELECT}
      >
        <option value="">All outcomes</option>
        {RAG_STATUS_OPTIONS.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>
      <select
        value={filters.judgeState}
        onChange={(e) => onChange({ ...filters, judgeState: e.target.value })}
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
      <button
        type="button"
        aria-pressed={filters.disagreement}
        onClick={() =>
          onChange({ ...filters, disagreement: !filters.disagreement })
        }
        className={`min-h-11 rounded-lg border px-3 text-sm font-medium transition-colors ${
          filters.disagreement
            ? "border-disagreement bg-disagreement/10 text-disagreement"
            : "border-border-strong text-text-secondary hover:border-text-tertiary hover:text-text-primary"
        }`}
      >
        Flash/frontier disagreement
      </button>
    </div>
  );
}
