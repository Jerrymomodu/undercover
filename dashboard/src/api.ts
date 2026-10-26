export type Status =
  "waiting" | "in_progress" | "awaiting_sign_off" | "decided";
export type Outcome = "approve" | "decline" | "refer";
export type StepKind = "tool_call" | "tool_result" | "reply" | "note";

export interface ClaimSummary {
  claim_id: string;
  customer_name: string;
  claim_type: string;
  amount_claimed: number;
  submitted_on: string;
  status: Status;
  decision: Outcome | null;
  payout: number | null;
}

export interface Decision {
  decision: Outcome;
  payout: number;
  reason: string;
  policy_section: string;
  decided_at: string;
}

export interface SignOff {
  handler_id: string;
  handler_name: string;
  signed_off_at: string;
}

export interface Payment {
  amount: number;
  paid_at: string;
}

export interface ClaimState {
  claim_id: string;
  status: Status;
  decision: Decision | null;
  sign_off: SignOff | null;
  payment: Payment | null;
}

export interface Claim extends ClaimState {
  policy_id: string;
  customer_id: string;
  claim_type: string;
  submitted_on: string;
  incident_date: string;
  incident_location: string;
  summary: string;
  story: string;
  items: { description: string; category: string; amount: number }[];
  amount_claimed: number;
  documents: { name: string; type: string; content: string }[];
}

export interface Plan {
  plan: string;
  name: string;
  per_item_limit: number;
  deductible: number;
}

export interface Policy {
  policy_id: string;
  plan: Plan;
  add_ons: { add_on: string; name: string; effect: string }[];
  purchased_on: string;
  trip: {
    destination: string;
    departs_on: string;
    returns_on: string;
    trip_cost: number;
  };
  travelers: string[];
}

export interface PreviousClaim {
  claim_id: string;
  filed_on: string;
  claim_type: string;
  summary: string;
  outcome: string;
  amount_paid: number;
}

export interface Customer {
  customer_id: string;
  name: string;
  email: string;
  phone: string;
  customer_since: string;
  previous_claims: PreviousClaim[];
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
  can_approve_over_limit: boolean;
}

export interface Step {
  step_id: number;
  thread_id: string;
  kind: StepKind;
  text: string;
  created_at: string;
}

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(
    path,
    body && {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `The backend replied ${String(response.status)}.`,
    );
  }
  return (await response.json()) as T;
}

export const api = {
  claims: () => request<ClaimSummary[]>("/api/claims"),
  claim: (id: string) => request<Claim>(`/api/claims/${id}`),
  policy: (id: string) => request<Policy>(`/api/policies/${id}`),
  customer: (id: string) => request<Customer>(`/api/customers/${id}`),
  steps: (id: string) => request<Step[]>(`/api/claims/${id}/steps`),
  handlers: () => request<Handler[]>("/api/handlers"),
  instructions: () => request<{ content: string }>("/api/instructions"),
  runAgent: (id: string) =>
    request<{ thread_id: string }>(`/api/claims/${id}/run`, {}),
  signOff: (id: string, handlerId: string) =>
    request<ClaimState>(`/api/claims/${id}/sign-off`, {
      handler_id: handlerId,
    }),
};
