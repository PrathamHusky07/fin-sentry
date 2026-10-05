import type { ReactNode } from "react";

/**
 * A thin-bordered layered panel -- the one container primitive the
 * application surface uses instead of SaaS-style drop-shadow cards (see
 * ../CLAUDE.md). Background-shift elevation only.
 */
export function Panel({
  children,
  className = "",
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  return (
    <Tag
      className={`border-border bg-background-elevated rounded-md border ${className}`}
    >
      {children}
    </Tag>
  );
}
