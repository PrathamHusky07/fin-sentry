import { GATEWAY_URL } from "@/lib/config";
import type {
  Detail,
  Listing,
  Started,
  Status,
  TriggerKind,
} from "@/lib/incidents";

/** A failed incident API call. `investigationId` is set on the 409 that says a different
 * investigation is already running, so the page can open that one instead. */
export class IncidentApiError extends Error {
  readonly status: number;
  readonly investigationId: string | null;

  constructor(message: string, status: number, investigationId: string | null) {
    super(message);
    this.status = status;
    this.investigationId = investigationId;
  }
}

function field(body: unknown, key: string): unknown {
  return typeof body === "object" && body !== null
    ? (body as Record<string, unknown>)[key]
    : undefined;
}

function messageFor(body: unknown, status: number): string {
  const error = field(body, "error");
  if (typeof error === "string") return error;
  const detail = field(body, "detail");
  if (Array.isArray(detail)) {
    const first: unknown = detail[0];
    const msg = field(first, "msg");
    return typeof msg === "string"
      ? `The request was not valid: ${msg}.`
      : "The request was not valid.";
  }
  return `The gateway returned ${status}.`;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${GATEWAY_URL}/ops/investigations${path}`, init);
  } catch {
    throw new IncidentApiError("The gateway could not be reached.", 0, null);
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const id = field(body, "investigation_id");
    throw new IncidentApiError(
      messageFor(body, res.status),
      res.status,
      typeof id === "string" ? id : null,
    );
  }
  return body as T;
}

export const fetchIncidents = (
  offset: number,
  status: Status | "",
  limit = 20,
) => {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (status) params.set("status", status);
  return call<Listing>(`?${params.toString()}`);
};

export const fetchIncident = (id: string) =>
  call<Detail>(`/${encodeURIComponent(id)}`);

export interface StartRequest {
  kind: TriggerKind;
  reference_id?: string;
  endpoint?: string;
  ticker?: string;
  window_minutes: number;
}

export const startIncident = (request: StartRequest) =>
  call<Started>("", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
