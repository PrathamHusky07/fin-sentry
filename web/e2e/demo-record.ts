import record from "../lib/demo-record.json";

/** The configured demonstration disagreement (lib/demo-record.json). The specs that need a real
 * flash and frontier disagreement in the store locate it through this one file and never carry
 * a trace id of their own. While the record is historical the original trace is not in the
 * store, so those specs are skipped with this reason and reported as skipped, not passed. */
export const DISAGREEMENT_TRACE_ID = record.disagreement.app_trace_id;
export const DISAGREEMENT_IS_LIVE = record.disagreement.origin === "live";
export const RERUN_TRACE_ID = record.reask.app_trace_id;
export const NO_LIVE_DISAGREEMENT =
  "The configured demonstration disagreement is historical: its trace expired from the event log and no real flash and frontier disagreement is stored. See web/lib/demo-record.json.";
