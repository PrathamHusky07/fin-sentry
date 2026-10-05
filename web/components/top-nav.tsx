"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ROUTES = [
  { href: "/", label: "Overview" },
  { href: "/operations", label: "Live Operations" },
  { href: "/investigations", label: "Investigations" },
  { href: "/red-team", label: "Red Team" },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Minimal operational nav -- no logo mark, no hero, just the real routes,
 * with the current one visually obvious. */
export function TopNav() {
  const pathname = usePathname();

  return (
    <header className="border-border border-b">
      <nav
        aria-label="Primary"
        className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 sm:px-6"
      >
        <Link
          href="/"
          className="text-text-primary focus-visible:outline-accent rounded-md text-sm font-semibold tracking-tight focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          Fin-Sentry
        </Link>
        <ul className="flex flex-wrap gap-1">
          {ROUTES.map((route) => {
            const active = isActive(pathname, route.href);
            return (
              <li key={route.href}>
                <Link
                  href={route.href}
                  aria-current={active ? "page" : undefined}
                  className={`focus-visible:outline-accent inline-flex min-h-11 items-center rounded-md px-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${
                    active
                      ? "text-text-primary bg-surface font-medium"
                      : "text-text-secondary hover:bg-surface hover:text-text-primary"
                  }`}
                >
                  {route.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
