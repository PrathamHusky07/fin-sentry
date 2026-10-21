"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Mark } from "@/components/mark";
import { ROUTES } from "@/lib/routes";

function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The global product shell: sticky, translucent, and present on every
 * route. Six destinations plus the wordmark (which is the presentation
 * route). Below the lg breakpoint the destinations collapse into a
 * disclosure menu; Escape closes it and returns focus to its button.
 */
export function TopNav() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setMenuOpen(false);
        menuButtonRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  return (
    <header className="border-border bg-background/75 sticky top-0 z-40 border-b backdrop-blur-xl backdrop-saturate-150">
      <nav
        aria-label="Primary"
        className="mx-auto flex h-14 w-full max-w-7xl items-center justify-between gap-4 px-4 sm:px-8"
      >
        <Link
          href="/"
          aria-current={pathname === "/" ? "page" : undefined}
          onClick={() => setMenuOpen(false)}
          className="text-text-primary -ml-2 flex min-h-11 items-center gap-2.5 rounded-md px-2 text-base font-semibold tracking-tight"
        >
          <Mark />
          Fin-Sentry
        </Link>

        <ul className="hidden items-center gap-0.5 lg:flex">
          {ROUTES.map((route) => {
            const active = isActive(pathname, route.href);
            return (
              <li key={route.href} className="relative">
                <Link
                  href={route.href}
                  aria-current={active ? "page" : undefined}
                  className={`inline-flex min-h-11 items-center rounded-md px-3.5 text-sm transition-colors ${
                    active
                      ? "text-text-primary font-medium"
                      : "text-text-secondary hover:text-text-primary hover:bg-surface"
                  }`}
                >
                  {route.label}
                </Link>
                {active ? (
                  <span
                    aria-hidden="true"
                    className="bg-accent absolute inset-x-3.5 -bottom-[9px] h-0.5 rounded-full"
                  />
                ) : null}
              </li>
            );
          })}
        </ul>

        <button
          ref={menuButtonRef}
          type="button"
          aria-expanded={menuOpen}
          aria-controls="mobile-nav"
          aria-label={
            menuOpen ? "Close navigation menu" : "Open navigation menu"
          }
          onClick={() => setMenuOpen((open) => !open)}
          className="text-text-primary hover:bg-surface -mr-2 flex h-11 w-11 items-center justify-center rounded-md lg:hidden"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            className="h-5 w-5"
            aria-hidden="true"
          >
            {menuOpen ? (
              <path d="M6 6l12 12M18 6L6 18" />
            ) : (
              <path d="M4 8h16M4 16h16" />
            )}
          </svg>
        </button>
      </nav>

      {menuOpen ? (
        <div
          id="mobile-nav"
          className="modal-in border-border bg-background-elevated/95 origin-top border-t backdrop-blur-xl lg:hidden"
        >
          <ul className="mx-auto flex max-w-7xl flex-col px-2 py-2 sm:px-6">
            {ROUTES.map((route) => {
              const active = isActive(pathname, route.href);
              return (
                <li key={route.href}>
                  <Link
                    href={route.href}
                    aria-current={active ? "page" : undefined}
                    onClick={() => setMenuOpen(false)}
                    className={`flex min-h-12 items-center justify-between rounded-md px-3 text-base ${
                      active
                        ? "text-text-primary bg-surface font-medium"
                        : "text-text-secondary hover:bg-surface hover:text-text-primary"
                    }`}
                  >
                    {route.label}
                    {active ? (
                      <span
                        aria-hidden="true"
                        className="bg-accent h-1.5 w-1.5 rounded-full"
                      />
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </header>
  );
}
