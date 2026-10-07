"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";

/**
 * A product capture presented as an inspectable window. The viewport has a
 * fixed height and the capture inside it is the full, real screenshot, so
 * scrolling the frame reveals more of the actual screen rather than a
 * different picture. The title bar names the real route and carries one
 * contextual action that opens that route. The chrome is presentation; the
 * image is a capture of the running application.
 */
export function BrowserFrame({
  src,
  alt,
  route,
  width,
  height,
  href,
  cta,
  priority = false,
}: {
  src: string;
  alt: string;
  route: string;
  /** Pixel size of the capture file. */
  width: number;
  height: number;
  /** The real route the action opens. */
  href: string;
  /** Verb phrase for the action, e.g. "Inspect disagreement". */
  cta: string;
  priority?: boolean;
}) {
  const [scrolled, setScrolled] = useState(false);
  const [atEnd, setAtEnd] = useState(false);
  const scrollable = height > width * 0.75;

  return (
    <div className="lift lift-accent reveal-host border-border-strong bg-background-elevated overflow-hidden rounded-xl border shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)]">
      <div className="border-border bg-surface flex items-center gap-3 border-b pr-2 pl-4">
        <span aria-hidden="true" className="hidden gap-1.5 sm:flex">
          <span className="bg-border-strong h-2.5 w-2.5 rounded-full" />
          <span className="bg-border-strong h-2.5 w-2.5 rounded-full" />
          <span className="bg-border-strong h-2.5 w-2.5 rounded-full" />
        </span>
        <span className="text-text-secondary bg-background border-border my-2.5 min-w-0 flex-1 truncate rounded-md border px-3 py-1 text-center font-mono text-xs">
          {route}
        </span>
        <Link
          href={href}
          className="reveal-on-hover text-accent hover:text-text-primary inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-md px-2 text-sm font-medium transition-colors"
        >
          {cta}
          <span aria-hidden="true">→</span>
        </Link>
      </div>
      <div className="relative">
        <div
          tabIndex={0}
          role="region"
          aria-label={`Scrollable capture of ${route}`}
          onScroll={(e) => {
            const el = e.currentTarget;
            setScrolled(el.scrollTop > 24);
            setAtEnd(el.scrollTop + el.clientHeight >= el.scrollHeight - 8);
          }}
          className="thin-scroll max-h-[24rem] overflow-y-auto overscroll-contain sm:max-h-[32rem]"
        >
          <Image
            src={src}
            alt={alt}
            width={width}
            height={height}
            priority={priority}
            sizes="(min-width: 1280px) 1100px, 100vw"
            className="block h-auto w-full"
          />
        </div>
        {scrollable ? (
          <>
            <div
              aria-hidden="true"
              className={`from-background-elevated pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t to-transparent transition-opacity duration-[var(--dur-base)] ${atEnd ? "opacity-0" : "opacity-100"}`}
            />
            <span
              aria-hidden="true"
              className={`bg-surface-floating/90 border-line-active text-text-secondary pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full border px-3 py-1 text-xs transition-opacity duration-[var(--dur-base)] ${scrolled || atEnd ? "opacity-0" : "opacity-100"}`}
            >
              Scroll the capture
            </span>
          </>
        ) : null}
      </div>
    </div>
  );
}
