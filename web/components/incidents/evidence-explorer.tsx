import { RecordChip } from "@/components/incidents/badges";
import {
  evidenceRows,
  kindLabel,
  type Claim,
  type Detail,
  type EvidenceRef,
  type EvidenceRow,
  type Origin,
} from "@/lib/incidents";

function Chips({ refs, origin }: { refs: EvidenceRef[]; origin: Origin }) {
  const records = refs.filter((r) => r.kind !== "query_result");
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {records.map((r) => (
        <RecordChip
          key={`${r.kind}:${r.record_id}`}
          record={r}
          origin={origin}
        />
      ))}
    </div>
  );
}

function ClaimList({
  title,
  note,
  claims,
  origin,
}: {
  title: string;
  note: string;
  claims: { statement: string; evidence: EvidenceRef[]; lead?: string }[];
  origin: Origin;
}) {
  // The investigator can state the same finding once per prediction, so identical claims
  // citing the same records are shown once.
  const unique = claims.filter(
    (c, i) =>
      claims.findIndex(
        (o) =>
          o.lead === c.lead &&
          o.statement === c.statement &&
          o.evidence.map((r) => r.kind + r.record_id).join() ===
            c.evidence.map((r) => r.kind + r.record_id).join(),
      ) === i,
  );
  if (unique.length === 0) return null;
  return (
    <div>
      <h3 className="text-text-primary text-lg font-semibold">{title}</h3>
      <p className="text-text-tertiary mt-0.5 text-sm">{note}</p>
      <ul className="mt-3 space-y-4">
        {unique.map((c, i) => (
          <li
            key={`${c.lead ?? ""}${i}`}
            className="border-border border-l-2 pl-4"
          >
            <p className="text-text-primary text-base leading-relaxed">
              {c.lead ? (
                <span className="text-text-tertiary font-mono">{c.lead} </span>
              ) : null}
              {c.statement}
            </p>
            <Chips refs={c.evidence} origin={origin} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function Facts({ facts }: { facts: EvidenceRow["facts"] }) {
  if (!facts) {
    return (
      <span className="text-text-tertiary text-sm">
        Not stored with this session
      </span>
    );
  }
  const shown = Object.entries(facts).filter(([, v]) => v !== null && v !== "");
  return (
    <span className="text-text-secondary font-mono text-xs break-words">
      {shown.map(([k, v]) => `${k}: ${String(v)}`).join("   ")}
    </span>
  );
}

function RecordsTable({
  rows,
  origin,
}: {
  rows: EvidenceRow[];
  origin: Origin;
}) {
  return (
    <>
      <table className="hidden w-full table-fixed text-left lg:table">
        <caption className="sr-only">
          Every record the report cites, with the role it plays, the hypotheses
          it is attached to, the queries that returned it and what the tool said
          about it when it was read.
        </caption>
        <thead className="text-text-tertiary text-sm">
          <tr className="border-border border-b">
            <th scope="col" className="w-[26%] py-2 pr-4 font-normal">
              Record
            </th>
            <th scope="col" className="w-[24%] py-2 pr-4 font-normal">
              Role
            </th>
            <th scope="col" className="w-[12%] py-2 pr-4 font-normal">
              Hypotheses
            </th>
            <th scope="col" className="w-[10%] py-2 pr-4 font-normal">
              Returned by
            </th>
            <th scope="col" className="py-2 font-normal">
              What the tool said when it was read
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-border border-b align-top">
              <td className="py-3 pr-4">
                <RecordChip record={r.ref} origin={origin} />
              </td>
              <td className="text-text-primary py-3 pr-4 text-base">
                {r.roles.join(", ")}
              </td>
              <td className="text-text-secondary py-3 pr-4 font-mono text-sm">
                {r.hypotheses.join(", ") || "none"}
              </td>
              <td className="py-3 pr-4 font-mono text-sm">
                {r.queryIds.map((id, i) => (
                  <span key={id}>
                    {i > 0 ? ", " : ""}
                    <a
                      href={`#${id}`}
                      className="text-accent inline-flex min-h-11 items-center underline underline-offset-4"
                    >
                      {id}
                    </a>
                  </span>
                ))}
              </td>
              <td className="py-3">
                <Facts facts={r.facts} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="divide-y divide-[var(--border)] lg:hidden">
        {rows.map((r) => (
          <li key={r.key} className="space-y-2 py-4">
            <RecordChip record={r.ref} origin={origin} />
            <p className="text-text-primary text-base">
              {kindLabel(r.ref.kind)}: {r.roles.join(", ")}
            </p>
            <p className="text-text-secondary text-sm">
              Attached to {r.hypotheses.join(", ") || "no hypothesis"}. Returned
              by {r.queryIds.join(", ") || "no recorded query"}.
            </p>
            <Facts facts={r.facts} />
          </li>
        ))}
      </ul>
    </>
  );
}

/** Every material claim in the report next to the exact records it cites. A citation is only
 * ever a record that a query in this investigation returned, which the backend validates
 * before it stores a report. A record's facts are what the tool returned when it was read. */
export function EvidenceExplorer({ detail }: { detail: Detail }) {
  const report = detail.report;
  const rows = evidenceRows(detail);
  const claim = (c: Claim) => ({
    statement: c.statement,
    evidence: c.evidence,
  });
  return (
    <section
      id="evidence"
      aria-labelledby="evidence-heading"
      className="scroll-mt-32"
    >
      <h2
        id="evidence-heading"
        className="text-text-primary text-2xl font-semibold tracking-tight"
      >
        Evidence
      </h2>
      {!report || rows.length === 0 ? (
        <p className="border-border-strong text-text-secondary mt-4 max-w-3xl rounded-xl border border-dashed px-5 py-8 text-base leading-relaxed">
          {report
            ? "The report cites no record. An abstention makes no claim, so there is nothing to link."
            : "No report was stored, so there are no claims to link to records."}
        </p>
      ) : (
        <div className="mt-4 space-y-10">
          <p className="text-text-secondary max-w-3xl text-base leading-relaxed">
            Each claim below lists the records it rests on. A record is linked
            to its own page when it was read from the live platform.
          </p>
          <ClaimList
            title="Observed"
            note="What the retrieved records show, without interpretation."
            claims={report.observations.map(claim)}
            origin={detail.origin}
          />
          <ClaimList
            title="Consistent with"
            note="A correlation, never a cause. The stored records cannot establish what caused the incident."
            claims={report.correlations.map(claim)}
            origin={detail.origin}
          />
          <ClaimList
            title="Cuts against"
            note="Records that argue against a hypothesis."
            claims={report.evidence_against.map((a) => ({
              statement: a.statement,
              evidence: a.evidence,
              lead: a.hypothesis_id,
            }))}
            origin={detail.origin}
          />
          <div>
            <h3 className="text-text-primary text-lg font-semibold">
              Every cited record ({rows.length})
            </h3>
            <div className="mt-3">
              <RecordsTable rows={rows} origin={detail.origin} />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
