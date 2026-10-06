import { DataTable, type DataTableColumn } from "@/components/data-table";
import { JudgeStateBadge } from "@/components/judge-state-badge";
import type { TraceListItem } from "@/lib/trace-api";

const RAG_STATUS_EMPHASIS: Record<string, string> = {
  blocked: "text-warning font-medium",
  error: "text-failure font-medium",
  success: "text-text-secondary",
};

/**
 * The real trace table, built on the shared sticky-header DataTable.
 * Distinct trace executions are never deduplicated here: four firings of
 * the same question are four real rows (the representative-aggregation
 * rule only applies to Overview/Live-Ops summary surfaces, see
 * ../lib/overview-data.ts).
 */
export function InvestigationsTable({
  traces,
  onSelect,
  selectedTraceId,
}: {
  traces: TraceListItem[];
  onSelect: (appTraceId: string) => void;
  selectedTraceId?: string | null;
}) {
  const columns: DataTableColumn<TraceListItem>[] = [
    {
      key: "time",
      header: "Time",
      cell: (t) => new Date(t.timestamp_utc).toLocaleString(),
      cellClassName: "text-text-secondary whitespace-nowrap",
    },
    {
      key: "query",
      header: "Query",
      cell: (t) => t.query,
      cellClassName: "text-text-primary max-w-xs truncate",
    },
    {
      key: "ticker",
      header: "Ticker",
      cell: (t) => t.ticker ?? "—",
      cellClassName: "text-text-secondary",
    },
    {
      key: "status",
      header: "Status",
      cell: (t) => (
        <span
          className={RAG_STATUS_EMPHASIS[t.rag_status] ?? "text-text-secondary"}
        >
          {t.rag_status}
          {t.block_reason ? ` (${t.block_reason})` : ""}
        </span>
      ),
    },
    {
      key: "judge_state",
      header: "Judge state",
      cell: (t) => <JudgeStateBadge state={t.judge_state} />,
    },
    {
      key: "frontier",
      header: "Frontier",
      cell: (t) => (t.frontier_sampled ? "Sampled" : "Not sampled"),
      cellClassName: "text-text-secondary",
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={traces}
      getRowKey={(t) => t.app_trace_id}
      onRowClick={(t) => onSelect(t.app_trace_id)}
      getRowLabel={(t) => `View trace: ${t.query}`}
      isSelected={(t) => t.app_trace_id === selectedTraceId}
    />
  );
}
