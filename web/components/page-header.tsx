import type { ReactNode } from "react";

/**
 * The shared page opener for the application routes: a mono eyebrow that
 * names the question the page answers, the title, and one sentence of
 * scope. Each route builds its own dominant composition below it.
 */
export function PageHeader({
  eyebrow,
  title,
  children,
  aside,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="max-w-2xl">
        <p className="eyebrow">{eyebrow}</p>
        <h1 className="text-text-primary mt-3 text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
          {title}
        </h1>
        {children ? (
          <p className="text-text-secondary mt-4 text-base leading-relaxed text-pretty">
            {children}
          </p>
        ) : null}
      </div>
      {aside ? <div className="shrink-0">{aside}</div> : null}
    </header>
  );
}
