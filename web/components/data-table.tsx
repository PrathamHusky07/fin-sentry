import type { ReactNode } from "react";

export interface DataTableColumn<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  /** Extra classes on every <td> in this column (e.g. width, truncation). */
  cellClassName?: string;
  headerClassName?: string;
}

/**
 * The one dense-scrollable-table primitive the application surface uses --
 * a controlled scroll region with a header that never scrolls away (the
 * "Excel freeze" behavior), row hover/selected/focus states, and keyboard
 * row activation. Built generic so every future dense table reuses this
 * instead of re-implementing sticky-header CSS per screen (Investigations'
 * trace table is the first consumer, not the only intended one).
 */
export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  onRowClick,
  getRowLabel,
  isSelected,
  maxHeight = "32rem",
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  getRowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  getRowLabel?: (row: T) => string;
  isSelected?: (row: T) => boolean;
  maxHeight?: string;
}) {
  return (
    <div
      className="border-border overflow-x-auto overflow-y-auto rounded-md border"
      style={{ maxHeight }}
    >
      <table className="w-full min-w-[40rem] text-left text-sm">
        <thead>
          <tr className="border-border bg-background-elevated text-text-secondary sticky top-0 z-10 border-b text-xs tracking-wide uppercase">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-3 py-2 font-medium ${col.headerClassName ?? ""}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = getRowKey(row);
            const selected = isSelected?.(row) ?? false;
            const interactive = onRowClick !== undefined;
            return (
              <tr
                key={key}
                onClick={interactive ? () => onRowClick(row) : undefined}
                onKeyDown={
                  interactive
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                tabIndex={interactive ? 0 : undefined}
                role={interactive ? "button" : undefined}
                aria-label={interactive ? getRowLabel?.(row) : undefined}
                aria-current={selected ? "true" : undefined}
                className={`border-border bg-background-elevated border-b outline-none last:border-b-0 ${
                  interactive
                    ? "hover:bg-surface focus-visible:outline-accent cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2"
                    : ""
                } ${selected ? "bg-accent/5 border-l-2 border-l-accent" : ""}`}
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={`px-3 py-2 ${col.cellClassName ?? ""}`}
                  >
                    {col.cell(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
