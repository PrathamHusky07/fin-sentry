"use client";

import { useState } from "react";

/** Copies `value` to the clipboard and says so. Used for trace ids, which
 * an engineer pastes into the MCP tools or a ticket. */
export function CopyButton({
  value,
  label,
  className = "",
}: {
  value: string;
  label: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy(event: React.MouseEvent) {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard access can be denied; the id stays selectable on screen.
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? "Copied" : label}
      className={`text-text-tertiary hover:text-text-primary hover:bg-surface-high inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md transition-colors ${className}`}
    >
      {copied ? (
        <svg
          viewBox="0 0 20 20"
          className="text-positive h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path d="M4 10.5l4 4 8-9" />
        </svg>
      ) : (
        <svg
          viewBox="0 0 20 20"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          aria-hidden="true"
        >
          <rect x="7" y="7" width="9" height="9" rx="1.5" />
          <path d="M13 7V5.5A1.5 1.5 0 0 0 11.5 4h-6A1.5 1.5 0 0 0 4 5.5v6A1.5 1.5 0 0 0 5.5 13H7" />
        </svg>
      )}
    </button>
  );
}
