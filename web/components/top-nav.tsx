import Link from "next/link";

const ROUTES = [
  { href: "/operations", label: "Live Operations" },
  { href: "/judges", label: "Judge Panel" },
  { href: "/red-team", label: "Red Team" },
] as const;

/** Minimal operational nav -- no logo mark, no hero, just the three routes. */
export function TopNav() {
  return (
    <header className="border-b border-neutral-200 dark:border-neutral-800">
      <nav aria-label="Primary" className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3 sm:px-6">
        <span className="text-sm font-semibold tracking-tight">Fin-Sentry</span>
        <ul className="flex gap-1">
          {ROUTES.map((route) => (
            <li key={route.href}>
              <Link
                href={route.href}
                className="inline-flex min-h-11 items-center rounded-md px-3 text-sm text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
              >
                {route.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </header>
  );
}
