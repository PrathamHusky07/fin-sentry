export interface InvestigationsFilterState {
  q: string;
  ticker: string;
  ragStatus: string;
  judgeState: string;
  frontierSampled: string;
  disagreement: boolean;
}

const RAG_STATUS_OPTIONS = ["success", "blocked", "error"] as const;
const JUDGE_STATE_OPTIONS = [
  { value: "evaluated", label: "Evaluated" },
  { value: "partially_evaluated", label: "Partially evaluated" },
  { value: "blocked_before_evaluation", label: "Blocked before evaluation" },
  { value: "judge_failed", label: "Judge pipeline error" },
  { value: "never_evaluated", label: "Not yet evaluated" },
] as const;

const SELECT_CLASS =
  "border-border bg-background-elevated text-text-primary focus-visible:outline-accent min-h-11 rounded-md border px-2 text-sm focus-visible:outline focus-visible:outline-2";
const INPUT_CLASS = SELECT_CLASS;

export function InvestigationsFilters({
  filters,
  onChange,
}: {
  filters: InvestigationsFilterState;
  onChange: (next: InvestigationsFilterState) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        type="search"
        value={filters.q}
        onChange={(e) => onChange({ ...filters, q: e.target.value })}
        placeholder="Search query text or trace ID"
        aria-label="Search query text or trace ID"
        className={`${INPUT_CLASS} min-w-0 flex-1 basis-56`}
      />
      <input
        type="text"
        value={filters.ticker}
        onChange={(e) => onChange({ ...filters, ticker: e.target.value })}
        placeholder="Ticker"
        aria-label="Filter by ticker"
        className={`${INPUT_CLASS} w-24`}
      />
      <select
        value={filters.ragStatus}
        onChange={(e) => onChange({ ...filters, ragStatus: e.target.value })}
        aria-label="Filter by status"
        className={SELECT_CLASS}
      >
        <option value="">All statuses</option>
        {RAG_STATUS_OPTIONS.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      <select
        value={filters.judgeState}
        onChange={(e) => onChange({ ...filters, judgeState: e.target.value })}
        aria-label="Filter by judge state"
        className={SELECT_CLASS}
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
        className={SELECT_CLASS}
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
        className={`focus-visible:outline-accent min-h-11 rounded-md border px-3 text-sm focus-visible:outline focus-visible:outline-2 ${
          filters.disagreement
            ? "border-failure bg-failure/10 text-failure"
            : "border-border hover:bg-surface text-text-secondary"
        }`}
      >
        Flash/frontier disagreement
      </button>
    </div>
  );
}
