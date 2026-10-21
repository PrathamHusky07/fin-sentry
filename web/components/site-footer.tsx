import Link from "next/link";
import { Mark } from "@/components/mark";

const LINK =
  "text-text-secondary hover:text-text-primary inline-flex min-h-11 min-w-11 items-center text-base transition-colors sm:text-sm";

/**
 * The one footer, rendered by the root layout so every route has it. A single row: the mark,
 * what the project is, the author and one outside link. Navigation lives in the top bar only.
 * It reports no status and no numbers, so it can never disagree with a page.
 */
export function SiteFooter() {
  return (
    <footer className="border-border border-t">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-x-8 gap-y-0 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:px-8">
        <div className="flex flex-col gap-x-5 gap-y-0 sm:flex-row sm:items-center">
          <Link
            href="/"
            className="text-text-primary -ml-2 inline-flex min-h-11 items-center gap-2.5 rounded-md px-2 text-base font-semibold tracking-tight"
          >
            <Mark />
            Fin-Sentry
          </Link>
          <p className="text-text-secondary text-base text-pretty sm:text-sm">
            Reliability and evaluation for production LLM systems.
          </p>
        </div>
        <div className="text-text-tertiary flex flex-wrap items-center gap-x-5 text-base sm:text-sm">
          <p>© 2026 Prathamesh Kulkarni</p>
          <a
            href="https://www.linkedin.com/in/prathameshkulkarni23/"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="LinkedIn (opens in a new tab)"
            className={LINK}
          >
            LinkedIn
          </a>
        </div>
      </div>
    </footer>
  );
}
