import { vi } from "vitest";
import type { ClaimSummary } from "./api";

/** Stub fetch with a reply for each "METHOD /path", and a 404 for the rest. */
export function stubApi(routes: Record<string, unknown>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = input instanceof Request ? input.url : input.toString();
    const route = `${init?.method ?? "GET"} ${path}`;
    const found = route in routes;
    return Promise.resolve(
      new Response(
        JSON.stringify(found ? routes[route] : { detail: `No ${route}` }),
        { status: found ? 200 : 404 },
      ),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function summary(overrides: Partial<ClaimSummary>): ClaimSummary {
  return {
    claim_id: "CLM-1001",
    customer_name: "Maya Patel",
    claim_type: "trip_delay",
    amount_claimed: 420,
    submitted_on: "2026-06-24",
    status: "waiting",
    decision: null,
    payout: null,
    ...overrides,
  };
}
