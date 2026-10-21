/** The product routes, in navigation order. The top bar reads this list, and routes.test.ts
 * checks that every entry has a page, so it cannot link to a route that does not exist. */
export const ROUTES = [
  { href: "/overview", label: "Overview" },
  { href: "/operations", label: "Live Operations" },
  { href: "/investigations", label: "Investigations" },
  { href: "/agent", label: "Agent" },
  { href: "/architecture", label: "Architecture" },
  { href: "/red-team", label: "Red Team" },
] as const;
