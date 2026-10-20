import Link from "next/link";

/** The two views of the Investigations area: one row per persisted execution, and one
 * session per incident the investigator examined. A plain pair of links, so the URL is the
 * state and the back button works. */
export function ViewSwitch({
  current,
}: {
  current: "executions" | "incidents";
}) {
  const items = [
    { key: "executions", href: "/investigations", label: "Executions" },
    { key: "incidents", href: "/investigations/incidents", label: "Incidents" },
  ] as const;
  return (
    <nav aria-label="Investigations views">
      <ul className="border-border-strong bg-background-elevated/60 inline-flex rounded-lg border p-1">
        {items.map((item) => {
          const active = item.key === current;
          return (
            <li key={item.key}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`inline-flex min-h-11 items-center rounded-md px-4 text-sm transition-colors ${active ? "bg-surface-high text-text-primary font-medium" : "text-text-secondary hover:text-text-primary"}`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
