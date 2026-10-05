import Link from "next/link";

const ROUTES = [
  { href: "/operations", label: "Live Operations" },
  { href: "/judges", label: "Judge Panel" },
  { href: "/red-team", label: "Red Team" },
] as const;

/** Minimal operational nav -- no logo mark, no hero, just the three routes. */
export function TopNav() {
  return (
    <header className="border-border border-b">
      <nav
        aria-label="Primary"
        className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3 sm:px-6"
      >
        <span className="text-text-primary text-sm font-semibold tracking-tight">
          Fin-Sentry
        </span>
        <ul className="flex gap-1">
          {ROUTES.map((route) => (
            <li key={route.href}>
              <Link
                href={route.href}
                className="text-text-secondary hover:bg-surface hover:text-text-primary focus-visible:outline-accent inline-flex min-h-11 items-center rounded-md px-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
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
