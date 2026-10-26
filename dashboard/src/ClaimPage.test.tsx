import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Claim, Step } from "./api";
import { ClaimPage } from "./ClaimPage";
import { stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CLAIM: Claim = {
  claim_id: "CLM-1001",
  status: "waiting",
  decision: null,
  sign_off: null,
  payment: null,
  policy_id: "POL-2001",
  customer_id: "CUS-3001",
  claim_type: "trip_delay",
  submitted_on: "2026-06-24",
  incident_date: "2026-06-18",
  incident_location: "Rome, Italy",
  summary: "Flight home canceled by the airline",
  story: "My flight home from Rome was canceled.",
  items: [
    { description: "Airport hotel", category: "accommodation", amount: 245 },
    { description: "Dinner and breakfast", category: "meals", amount: 95 },
  ],
  amount_claimed: 340,
  documents: [
    {
      name: "Hotel receipt",
      type: "receipt",
      content: "Hotel Aurelia. $245.00.",
    },
  ],
};

const APPROVED = {
  decision: "approve" as const,
  payout: 1250,
  reason: "The bag was stolen and reported.",
  policy_section: "5. Baggage and Personal Effects",
  decided_at: "2026-10-26T10:00:00+00:00",
};

const ROUTES = {
  "GET /api/policies/POL-2001": {
    policy_id: "POL-2001",
    plan: { plan: "premium", name: "UnderCover Premium" },
    add_ons: [],
    purchased_on: "2026-04-22",
    trip: {
      destination: "Rome, Italy",
      departs_on: "2026-06-10",
      returns_on: "2026-06-18",
      trip_cost: 3100,
    },
    travelers: ["Maya Patel"],
  },
  "GET /api/customers/CUS-3001": {
    customer_id: "CUS-3001",
    name: "Maya Patel",
    email: "maya.patel@example.com",
    phone: "+1 201 555 0143",
    customer_since: "2023-04-11",
    previous_claims: [
      {
        claim_id: "CLM-0412",
        filed_on: "2024-08-19",
        claim_type: "baggage_delay",
        summary: "Checked bag arrived 30 hours late in Lisbon",
        outcome: "approved",
        amount_paid: 140,
      },
    ],
  },
  "GET /api/handlers": [
    {
      handler_id: "HND-01",
      name: "Dana Whitfield",
      role: "Senior Claims Handler",
      can_approve_over_limit: true,
    },
  ],
};

function show(claim: Partial<Claim>, steps: Step[] = [], extra = {}) {
  const fetchMock = stubApi({
    ...ROUTES,
    "GET /api/claims/CLM-1001": { ...CLAIM, ...claim },
    "GET /api/claims/CLM-1001/steps": steps,
    ...extra,
  });
  render(<ClaimPage claimId="CLM-1001" />);
  return fetchMock;
}

it("shows a claim in full", async () => {
  show({});
  expect(
    await screen.findByText("My flight home from Rome was canceled."),
  ).toBeDefined();
  expect(screen.getByText("Flight home canceled by the airline")).toBeDefined();
  expect(screen.getByText("Airport hotel")).toBeDefined();
  expect(screen.getByText("$340.00")).toBeDefined();
  expect(screen.getByText("Hotel Aurelia. $245.00.")).toBeDefined();
  expect(await screen.findByText("UnderCover Premium")).toBeDefined();
  expect(await screen.findByText(/CLM-0412/)).toBeDefined();
  expect(screen.getByText(/Checked bag arrived 30 hours late/)).toBeDefined();
  expect(screen.getByText("No decision yet.")).toBeDefined();
  expect(
    screen.getByText("The agent hasn't worked on this claim yet."),
  ).toBeDefined();
});

it("runs the agent on a waiting claim", async () => {
  const fetchMock = show({}, [], {
    "POST /api/claims/CLM-1001/run": { thread_id: "thread-1" },
  });
  fireEvent.click(await screen.findByRole("button", { name: "Run the agent" }));
  await vi.waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/claims/CLM-1001/run",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

it("says when the agent can't be started", async () => {
  show({});
  fireEvent.click(await screen.findByRole("button", { name: "Run the agent" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "No POST /api/claims/CLM-1001/run",
  );
});

it("shows the agent's steps while it works", async () => {
  show({ status: "in_progress" }, [
    {
      step_id: 1,
      thread_id: "thread-1",
      kind: "note",
      text: "The agent started work on the claim.",
      created_at: "2026-10-26T10:00:00+00:00",
    },
    {
      step_id: 2,
      thread_id: "thread-1",
      kind: "tool_call",
      text: 'get_claim {"claim_id": "CLM-1001"}',
      created_at: "2026-10-26T10:00:01+00:00",
    },
  ]);
  const steps = await screen.findByRole("list", { name: "" });
  expect(
    within(steps)
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).toEqual([
    "NoteThe agent started work on the claim.",
    'Calledget_claim {"claim_id": "CLM-1001"}',
  ]);
  expect(screen.getByText("The agent is working")).toBeDefined();
  expect(screen.queryByRole("button", { name: "Run the agent" })).toBeNull();
});

it("shows a decided claim with its decision and payment", async () => {
  show({
    status: "decided",
    decision: { ...APPROVED, payout: 420 },
    payment: { amount: 420, paid_at: "2026-10-26T10:00:05+00:00" },
  });
  expect(await screen.findByText("Approved")).toBeDefined();
  expect(screen.getByText("The bag was stolen and reported.")).toBeDefined();
  expect(
    screen.getByText("Policy section: 5. Baggage and Personal Effects"),
  ).toBeDefined();
  expect(screen.getByText("Paid $420.00 on Oct 26, 2026.")).toBeDefined();
});

it("shows a declined claim without a payment", async () => {
  show({
    status: "decided",
    decision: { ...APPROVED, decision: "decline", payout: 0 },
  });
  expect(await screen.findByText("Declined")).toBeDefined();
  expect(screen.queryByText(/Paid/)).toBeNull();
});

it("signs off a payout over the limit", async () => {
  const fetchMock = show(
    { status: "awaiting_sign_off", decision: APPROVED },
    [],
    {
      "POST /api/claims/CLM-1001/sign-off": {},
    },
  );
  const button = await screen.findByRole("button", {
    name: "Sign off and pay $1,250.00",
  });
  expect(button).toHaveProperty("disabled", true);

  await screen.findByRole("option", { name: "Dana Whitfield" });
  fireEvent.change(screen.getByLabelText("Handler"), {
    target: { value: "HND-01" },
  });
  fireEvent.click(button);
  await vi.waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/claims/CLM-1001/sign-off",
      expect.objectContaining({ body: '{"handler_id":"HND-01"}' }),
    );
  });
});

it("says when a sign-off is refused", async () => {
  show({ status: "awaiting_sign_off", decision: APPROVED });
  await screen.findByRole("option", { name: "Dana Whitfield" });
  fireEvent.change(screen.getByLabelText("Handler"), {
    target: { value: "HND-01" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Sign off and pay $1,250.00" }),
  );
  expect((await screen.findByRole("alert")).textContent).toBe(
    "No POST /api/claims/CLM-1001/sign-off",
  );
});

it("shows a claim signed off and paid", async () => {
  show({
    status: "decided",
    decision: APPROVED,
    sign_off: {
      handler_id: "HND-01",
      handler_name: "Dana Whitfield",
      signed_off_at: "2026-10-26T11:00:00+00:00",
    },
    payment: { amount: 1250, paid_at: "2026-10-26T11:00:00+00:00" },
  });
  expect(
    await screen.findByText(
      "Paid $1,250.00 on Oct 26, 2026, signed off by Dana Whitfield.",
    ),
  ).toBeDefined();
});

it("says when the claim can't be loaded", async () => {
  stubApi({});
  render(<ClaimPage claimId="CLM-9999" />);
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Couldn't load CLM-9999: No GET /api/claims/CLM-9999",
  );
});
