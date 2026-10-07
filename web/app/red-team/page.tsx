import type { Metadata } from "next";
import Link from "next/link";
import { FlowChain } from "@/components/flow-chain";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = {
  title: "Red Team — Fin-Sentry",
};

/**
 * Not built, and shown as not built. There is no stored scenario registry
 * and the MCP server’s run_red_team_scenario tool is deliberately left
 * unregistered (finsentry/mcp/server.py), so there is nothing real to fire.
 * This route describes the intended loop as a dashed outline and points to
 * the adversarial evidence that does exist today.
 */
export default function RedTeamPage() {
  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-8 sm:py-16">
      <PageHeader eyebrow="Adversarial testing" title="Red Team">
        A console for firing stored adversarial scenarios at the gateway and
        watching them evaluated like any other request.
      </PageHeader>

      <div className="mt-8 flex items-center gap-3">
        <span className="border-warning/40 bg-warning/10 text-warning inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-medium tracking-wide uppercase">
          Not built
        </span>
        <span className="text-text-secondary text-sm">
          Nothing on this page is a mock. There is nothing to run yet.
        </span>
      </div>

      <section
        aria-labelledby="loop-heading"
        className="border-border-strong mt-12 rounded-2xl border border-dashed p-6 sm:p-10"
      >
        <p className="eyebrow">Planned loop</p>
        <h2
          id="loop-heading"
          className="text-text-primary mt-2 text-2xl font-semibold tracking-tight"
        >
          What the console would do
        </h2>
        <div className="mt-8">
          <FlowChain
            edge="sync"
            label="Planned red team loop, not built"
            steps={[
              {
                label: "Scenario registry",
                sub: "Stored adversarial prompts",
                tone: "muted",
                dashed: true,
                chips: [
                  "Direct prompt injection",
                  "Indirect prompt injection",
                  "Jailbreak attempts",
                  "Prompt leakage",
                ],
              },
              {
                label: "Fire at the gateway",
                sub: "The same endpoint real traffic uses",
                tone: "muted",
                dashed: true,
              },
              {
                label: "Rails and judges",
                sub: "Evaluated like any other request",
                tone: "muted",
                dashed: true,
              },
              {
                label: "Result",
                sub: "Caught, missed, or blocked for the wrong reason",
                tone: "muted",
                dashed: true,
              },
            ]}
          />
        </div>
      </section>

      <div className="mt-16 grid gap-x-16 gap-y-12 lg:grid-cols-2">
        <section aria-labelledby="missing-heading">
          <h2
            id="missing-heading"
            className="text-text-primary text-xl font-semibold tracking-tight"
          >
            What is missing
          </h2>
          <dl className="border-border mt-5 border-t">
            <div className="border-border border-b py-4">
              <dt className="text-text-primary text-base font-medium">
                No scenario registry
              </dt>
              <dd className="text-text-secondary mt-1 text-base leading-relaxed">
                No stored set of adversarial scenarios exists in the project.
              </dd>
            </div>
            <div className="border-border border-b py-4">
              <dt className="text-text-primary text-base font-medium">
                The MCP tool is unregistered
              </dt>
              <dd className="text-text-secondary mt-1 text-base leading-relaxed">
                <span className="font-mono text-sm">run_red_team_scenario</span>{" "}
                is left out of the MCP server on purpose, because registering it
                over an empty registry would expose a tool that does nothing.
              </dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="exists-heading">
          <h2
            id="exists-heading"
            className="text-text-primary text-xl font-semibold tracking-tight"
          >
            Adversarial evidence that does exist
          </h2>
          <p className="text-text-secondary mt-5 text-base leading-relaxed">
            The input rails do run on every real request, and blocks they
            produce are persisted with the rail that fired. Open the blocked
            executions to see them, or read how the rails are built.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              href="/investigations?status=blocked"
              className="border-border-strong text-text-primary hover:bg-surface inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-medium transition-colors"
            >
              Open blocked executions
              <span aria-hidden="true">→</span>
            </Link>
            <Link
              href="/architecture#request-path"
              className="border-border-strong text-text-primary hover:bg-surface inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-medium transition-colors"
            >
              Read the request path
              <span aria-hidden="true">→</span>
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}
