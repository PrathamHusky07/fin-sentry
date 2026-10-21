"use client";

import { useEffect, useState } from "react";

export interface RailSection {
  id: string;
  label: string;
}

/** Which section is under the top of the viewport. */
function useActive(ids: string[]): string | null {
  const [active, setActive] = useState<string | null>(null);
  const key = ids.join("|");
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id);
        }
      },
      { rootMargin: "-25% 0px -65% 0px" },
    );
    for (const id of key.split("|")) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [key]);
  return active;
}

/** A slim bar that sticks under the global navigation, so the reader always knows which
 * section is on screen and can jump to another. The anchors are plain links. */
export function SectionRail({ sections }: { sections: RailSection[] }) {
  const active = useActive(sections.map((s) => s.id));
  return (
    <nav
      aria-label="Jump to a section"
      data-sticky-rail
      className="border-border bg-background/80 sticky top-[var(--nav-h)] z-30 border-b backdrop-blur-xl"
    >
      <ul className="thin-scroll mx-auto flex max-w-7xl gap-1 overflow-x-auto px-2 sm:px-6">
        {sections.map((s) => {
          const current = active === s.id;
          return (
            <li key={s.id} className="relative shrink-0">
              <a
                href={`#${s.id}`}
                aria-current={current ? "location" : undefined}
                className={`flex min-h-11 items-center px-3 text-base transition-colors sm:text-sm duration-[var(--dur-base)] ${current ? "text-text-primary font-medium" : "text-text-secondary hover:text-text-primary"}`}
              >
                {s.label}
              </a>
              <span
                aria-hidden="true"
                className={`bg-accent absolute inset-x-3 bottom-0 h-0.5 origin-left rounded-full transition-transform duration-[var(--dur-base)] ease-[var(--ease)] ${current ? "scale-x-100" : "scale-x-0"}`}
              />
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
