import Link from "next/link";
import { Mark } from "@/components/mark";
import { ROUTES } from "@/lib/routes";

/**
 * The one footer, rendered by the root layout so every route has it. It states what the
 * project is and links to the same routes as the top bar. It reports no status and no
 * numbers, so it can never disagree with a page.
 */
export function SiteFooter() {
  return (
    <footer className="border-border border-t">
      <div className="mx-auto grid w-full max-w-7xl gap-6 px-4 py-8 sm:px-8 sm:py-10 lg:grid-cols-[minmax(0,26rem)_1fr] lg:gap-20">
        <div>
          <Link
            href="/"
            className="text-text-primary -ml-2 inline-flex min-h-11 items-center gap-2.5 rounded-md px-2 text-base font-semibold tracking-tight"
          >
            <Mark />
            Fin-Sentry
          </Link>
          <p className="text-text-secondary mt-1 text-base leading-relaxed text-pretty sm:text-sm">
            Reliability and evaluation for production LLM systems. Financial RAG
            over SEC filings is the reference workload.
          </p>
        </div>
        <nav aria-label="Footer">
          <ul className="grid grid-cols-2 gap-x-6 sm:grid-cols-3 lg:w-max lg:grid-cols-[repeat(3,max-content)] lg:gap-x-12 lg:justify-self-end">
            {ROUTES.map((route) => (
              <li key={route.href}>
                <Link
                  href={route.href}
                  className="text-text-secondary hover:text-text-primary inline-flex min-h-11 items-center text-base transition-colors sm:text-sm"
                >
                  {route.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
      <div className="border-border border-t">
        <div className="text-text-tertiary mx-auto flex w-full max-w-7xl flex-col gap-1 px-4 py-5 text-base sm:flex-row sm:justify-between sm:px-8 sm:text-sm">
          <p>
            Fin-Sentry is a portfolio project. All data shown comes from a
            demonstration corpus of ten SEC filers.
          </p>
          <p>Built with Next.js, FastAPI, Redpanda and RisingWave.</p>
        </div>
      </div>
    </footer>
  );
}
