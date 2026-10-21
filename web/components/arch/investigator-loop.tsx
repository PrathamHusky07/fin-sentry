import {
  ArchLegend,
  ArrowDefs,
  Box,
  Edge,
  Label,
  LaneOutline,
  Region,
} from "@/components/arch/svg-parts";
import {
  DiagramScope,
  NodeDetailStrip,
  type NodeDetail,
} from "@/components/arch/node-model";
import { LAYERS } from "@/lib/architecture-layers";

const P = "inv";

const EDGES: [string, string][] = [
  ["trigger", "open"],
  ["open", "plan"],
  ["plan", "planner"],
  ["planner", "plan"],
  ["plan", "execute"],
  ["execute", "tools"],
  ["tools", "execute"],
  ["execute", "assess"],
  ["assess", "plan"],
  ["assess", "validate"],
  ["validate", "diagnosis"],
  ["open", "abstention"],
  ["plan", "abstention"],
  ["assess", "abstention"],
  ["validate", "abstention"],
];

const DETAILS: Record<string, NodeDetail> = {
  trigger: {
    title: "Trigger",
    text: "An investigation starts from one incident: a cluster of blocked requests, a surge of errors, judges that disagree, drift, a missed Red Team scenario or a single trace. It carries a scope and a time window, and it is stored before any work starts.",
  },
  open: {
    title: "Open",
    text: "The first read is of the one source the investigation cannot do without, asked about the trigger's own scope and window. If that source cannot run twice in a row, the investigation stops as critical evidence unavailable. If it matched nothing, the trigger left no record to examine, and the investigation abstains.",
  },
  plan: {
    title: "Plan",
    text: "The planner is shown a digest of counts, rails, tickers and a few ids, never a raw payload. It returns two to four rival hypotheses, each with predictions that name a closed signal, a tool and the query that would show it. Validation drops what the tool surface does not support and keeps only queries where two hypotheses predict differently. The model is called at most twice.",
  },
  planner: {
    title: "Planner (the model)",
    text: "The model proposes. It decides nothing and cites nothing. Its reply is untrusted structured data that code validates before any of it is used, and a failure or a timeout ends the plan, not the investigation's honesty.",
  },
  execute: {
    title: "Execute",
    text: "Code runs the kept queries, most discriminating first. Every call is admitted by a policy: a ceiling of eight tool calls, a wall-clock deadline, no identical repeat, and one justified retry of an unavailable source. A query that reads sampled traces first runs, or reuses, the listing the sample comes from.",
  },
  tools: {
    title: "Nine read-only tools",
    text: "The MCP tools for failing traces, guardrail decisions, judge scores, injection search, the drift report, trace search, trace detail and the two Red Team execution reads. The client refuses to connect unless the server offers exactly these nine, each marked read-only. There is no tool that writes.",
  },
  assess: {
    title: "Assess",
    text: "Deterministic evaluators read each prediction against the results of the query it names and nothing else. A prediction is met, unmet or unknown. The ledger sets each hypothesis supported, weakened, refuted or open from records only, checks that the records can bear on the hypothesis's subsystem, and a review then challenges the leader. If the evidence did not settle it and budget remains, the loop goes round once more.",
  },
  validate: {
    title: "Validate",
    text: "The report is checked against the investigation that produced it. Every citation must be a record that one of its queries returned. A record that merely shows a query ran backs no claim, a controlled test cannot support a production cause, and the ranking must match the ledger. A report that fails becomes an abstention.",
  },
  diagnosis: {
    title: "Diagnosis",
    text: "The best-supported hypothesis, written as a correlation with its supporting and contradicting records, the evidence that was missing, and one proposed verification that is never run. It is not a proven cause.",
  },
  abstention: {
    title: "Abstention",
    text: "A complete, valid result: the stopping reason, what was and was not available, and one proposed verification. The investigation exits here when a critical source is down, when nothing matched, when no plan was usable, when the budget is spent, when the records support no hypothesis, or when the report fails validation. Both outcomes are stored as a durable session.",
  },
};

const CAPTIONS = {
  sync: "Control flow, always run by code",
  async: "Proposal from the model, validated before any use",
  read: "Read-only query to the platform",
  muted: "Exit to an abstention",
} as const;

/**
 * Diagram 5, the Incident Response Agent, drawn as a control-flow state machine. It is the
 * one diagram on the page that loops. Code owns every state and every transition. The model
 * sits left of a hard line, the evidence boundary: it proposes hypotheses and the queries that
 * would tell them apart, and nothing it writes can be cited. Everything right of the line
 * is deterministic. The loop from Assess back to Plan runs at most once. Dashed grey exits
 * all end in the same place, an abstention, because a stop with a stated reason is a result.
 *
 * It was drawn from the implemented modules: the loop in investigator/loop.py (open, plan,
 * execute, reassess, diagnose or abstain), planning.py (the plan contract and
 * validate_plan), policy.py (admission, ceilings and the stopping order), signals.py and
 * ledger.py (the evaluators, the ledger and the review), citations.py (report validation),
 * mcp_client.py and adapter.py (the nine read-only tools), and store.py and service.py (the
 * durable session). Those paths are comments here and never appear on the page.
 */
export function IncidentResponseAgentLoop() {
  const lane = LAYERS.find((l) => l.id === "incident-response-agent");
  return (
    <div>
      <DiagramScope edges={EDGES} details={DETAILS}>
        <div className="hidden lg:block">
          <svg
            viewBox="0 0 1200 740"
            role="img"
            aria-label="The Incident Response Agent as a control-flow state machine. A trigger opens an investigation. Open reads the one critical source. Plan asks the model, which sits left of the evidence boundary, for rival hypotheses and the queries that tell them apart. Execute runs those queries through nine read-only tools. Assess reads each prediction against its own query's records and challenges the leader, and may loop back to Plan once. Validate checks every citation. The result is a diagnosis or an abstention, and four exits lead straight to an abstention."
            className="h-auto w-full"
          >
            <ArrowDefs prefix={P} />

            <Region
              x={318}
              y={24}
              w={742}
              h={592}
              label="Orchestrator, in code: 8 tool calls, 2 model calls, 3 rounds, 120 seconds"
              tone="request"
              dashed={false}
            />

            {/* The evidence boundary: the dominant line of the diagram. */}
            <line
              x1={292}
              y1={20}
              x2={292}
              y2={720}
              stroke="var(--text-primary)"
              strokeWidth={3}
              strokeDasharray="12 7"
              strokeOpacity={0.7}
            />
            <text
              x={282}
              y={52}
              textAnchor="end"
              fontSize={13}
              fontWeight={600}
              className="fill-text-primary"
            >
              Evidence boundary
            </text>
            <text
              x={282}
              y={72}
              textAnchor="end"
              fontSize={12}
              className="fill-text-secondary"
            >
              The model proposes,
            </text>
            <text
              x={282}
              y={88}
              textAnchor="end"
              fontSize={12}
              className="fill-text-secondary"
            >
              nothing it says is evidence
            </text>

            <Box
              x={36}
              y={398}
              w={190}
              h={92}
              id="planner"
              title="Planner"
              lines={["a model, at most", "two calls"]}
              tone="evaluation"
              dashed
            />

            <Box
              x={350}
              y={60}
              w={190}
              h={84}
              id="trigger"
              title="Trigger"
              lines={["incident, scope,", "time window"]}
              tone="stream"
            />
            <Box
              x={350}
              y={214}
              w={190}
              h={84}
              id="open"
              title="Open"
              lines={["read the critical", "source first"]}
              tone="request"
            />
            <Box
              x={350}
              y={398}
              w={190}
              h={92}
              id="plan"
              title="Plan"
              lines={["rival hypotheses,", "validated"]}
              tone="request"
            />
            <Box
              x={620}
              y={398}
              w={190}
              h={92}
              id="execute"
              title="Execute"
              lines={["queries that tell", "hypotheses apart"]}
              tone="request"
            />
            <Box
              x={890}
              y={398}
              w={150}
              h={92}
              id="assess"
              title="Assess"
              lines={["predictions vs", "own records"]}
              tone="request"
            />
            <Box
              x={890}
              y={214}
              w={150}
              h={84}
              id="validate"
              title="Validate"
              lines={["every citation", "is a real record"]}
              tone="request"
            />
            <Box
              x={620}
              y={520}
              w={190}
              h={76}
              id="tools"
              title="Nine read-only tools"
              lines={["MCP, no write path"]}
              tone="evidence"
            />
            <Box
              x={1084}
              y={214}
              w={96}
              h={84}
              id="diagnosis"
              title="Diagnosis"
              lines={["best", "supported"]}
              tone="evidence"
            />
            <Box
              x={350}
              y={644}
              w={690}
              h={70}
              id="abstention"
              title="Abstention"
              lines={[
                "a complete, valid result: the stopping reason, what was missing, one proposed verification",
              ]}
              tone="evidence"
            />

            {/* Main control flow. */}
            <Edge
              prefix={P}
              kind="sync"
              from="trigger"
              to="open"
              d="M445,144 V210"
            />
            <Edge
              prefix={P}
              kind="sync"
              from="open"
              to="plan"
              d="M445,298 V394"
            />
            <Edge
              prefix={P}
              kind="sync"
              from="plan"
              to="execute"
              d="M540,444 H616"
            />
            <Edge
              prefix={P}
              kind="sync"
              from="execute"
              to="assess"
              d="M810,444 H886"
            />
            <Edge
              prefix={P}
              kind="sync"
              from="assess"
              to="validate"
              d="M965,394 V302"
            />
            <Edge
              prefix={P}
              kind="sync"
              from="validate"
              to="diagnosis"
              d="M1040,256 H1080"
            />
            {/* The loop: once more, when budget remains and the evidence did not settle it. */}
            <Edge
              prefix={P}
              kind="sync"
              from="assess"
              to="plan"
              d="M915,394 V350 H495 V394"
            />
            <Label x={705} y={340} edge={["assess", "plan"]}>
              continue: one more round, if budget remains
            </Label>
            <Label x={455} y={196} anchor="start" edge={["trigger", "open"]}>
              stored, then started
            </Label>
            <Label x={455} y={322} anchor="start" edge={["open", "plan"]}>
              the trigger left a record
            </Label>

            {/* Across the evidence boundary. */}
            <Edge
              prefix={P}
              kind="async"
              from="plan"
              to="planner"
              d="M350,424 H230"
            />
            <Edge
              prefix={P}
              kind="async"
              from="planner"
              to="plan"
              d="M230,462 H346"
            />
            <Label x={258} y={414} anchor="middle" edge={["plan", "planner"]}>
              digest
            </Label>
            <Label x={288} y={484} anchor="end" edge={["planner", "plan"]}>
              plan
            </Label>

            {/* Reads. */}
            <Edge
              prefix={P}
              kind="read"
              from="execute"
              to="tools"
              d="M690,490 V516"
            />
            <Edge
              prefix={P}
              kind="read"
              from="tools"
              to="execute"
              d="M750,516 V494"
            />
            <Label x={680} y={510} anchor="end" edge={["execute", "tools"]}>
              query
            </Label>
            <Label x={760} y={510} anchor="start" edge={["tools", "execute"]}>
              records
            </Label>

            {/* Exits to an abstention. */}
            <Edge
              prefix={P}
              kind="muted"
              from="open"
              to="abstention"
              d="M350,256 H312 V679 H346"
            />
            <Edge
              prefix={P}
              kind="muted"
              from="plan"
              to="abstention"
              d="M445,490 V640"
            />
            <Edge
              prefix={P}
              kind="muted"
              from="assess"
              to="abstention"
              d="M965,490 V640"
            />
            <Edge
              prefix={P}
              kind="muted"
              from="validate"
              to="abstention"
              d="M1020,214 V178 H1192 V679 H1044"
            />
            <Label x={320} y={566} anchor="start" edge={["open", "abstention"]}>
              source down
            </Label>
            <Label x={320} y={582} anchor="start" edge={["open", "abstention"]}>
              or nothing matched
            </Label>
            <Label x={455} y={590} anchor="start" edge={["plan", "abstention"]}>
              no usable plan
            </Label>
            <Label
              x={975}
              y={600}
              anchor="start"
              edge={["assess", "abstention"]}
            >
              no support, or budget spent
            </Label>
            <Label
              x={1186}
              y={420}
              anchor="end"
              edge={["validate", "abstention"]}
            >
              a citation failed
            </Label>
          </svg>
          <NodeDetailStrip hint="Point at a state, or select one, to see what code does there and where it can exit." />
          <ArchLegend
            items={["sync", "async", "read", "muted"]}
            captions={CAPTIONS}
          />
        </div>
      </DiagramScope>
      <div className="lg:hidden">
        <LaneOutline lanes={lane ? lane.outline : []} />
      </div>
    </div>
  );
}
