import type { ReactNode } from "react";

/**
 * The one container primitive the application surface uses. Elevation is a
 * background shift plus a hairline border, never a drop shadow. Use it for
 * content that genuinely needs a boundary, not as a default wrapper: most
 * sections in this app sit directly on the page background.
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
      className={`border-border bg-background-elevated rounded-lg border ${className}`}
    >
      {children}
    </Tag>
  );
}
