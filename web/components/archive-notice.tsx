"use client";

import { usePathname } from "next/navigation";
import {
  ARCHIVE_NOTICE_BODY,
  ARCHIVE_NOTICE_LEAD,
  ARCHIVE_ROUTES,
} from "@/lib/archive-mode";

/**
 * The one line every page that reads from the archive carries, so a visitor never has to infer
 * that the records are recorded and not live. Rendered by the root layout only in archived mode.
 */
export function ArchiveNotice() {
  const pathname = usePathname();
  const onArchivedRoute = ARCHIVE_ROUTES.some(
    (route) => pathname === route || pathname.startsWith(`${route}/`),
  );
  if (!onArchivedRoute) return null;
  return (
    <div
      role="note"
      data-archive-notice
      className="border-border bg-background-elevated/70 border-b"
    >
      <p className="text-text-secondary mx-auto w-full max-w-7xl px-4 py-2 text-base leading-snug sm:px-8 sm:text-sm">
        <strong className="text-text-primary font-semibold">
          {ARCHIVE_NOTICE_LEAD}
        </strong>{" "}
        {ARCHIVE_NOTICE_BODY}
      </p>
    </div>
  );
}
