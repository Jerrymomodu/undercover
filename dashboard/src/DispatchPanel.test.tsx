import { act, cleanup, fireEvent, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Run } from "./api";
import {
  Refusal,
  type Routes,
  summary as claimSummary,
  panel,
  renderAt,
  stubApi,
} from "./testing";
import { REFRESH_MS } from "./useLoad";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const running: Run = {
  run_id: "run-1",
  number: 4,
  kind: "dispatch",
  agents: 3,
  status: "running",
  started_at: "2026-11-14T17:02:13+00:00",
  finished_at: null,
  eval_set: null,
  tiny: null,
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
  claims: [
    {
      claim_id: "CLM-1001",
      status: "decided",
      decision: "approve",
      payout: 420,
    },
    {
      claim_id: "CLM-1008",
      status: "in_progress",
      decision: null,
      payout: null,
    },
  ],
  summary: {
    approved: 1,
    declined: 0,
    referred: 0,
    waiting_for_sign_off: [],
    left_for_handler: [],
    in_progress: ["CLM-1008"],
    waiting: [],
  },
  cost: 0.01234,
  agent_seconds: 75.4,
};

const finished: Run = {
  ...running,
  status: "finished",
  finished_at: "2026-11-14T17:03:05+00:00",
  claims: [
    {
      claim_id: "CLM-1001",
      status: "decided",
      decision: "approve",
      payout: 420,
    },
    {
      claim_id: "CLM-1008",
      status: "waiting_for_sign_off",
      decision: "approve",
      payout: 2240,
    },
    { claim_id: "CLM-1010", status: "decided", decision: "decline", payout: 0 },
    {
      claim_id: "CLM-1018",
      status: "left_for_handler",
      decision: null,
      payout: null,
    },
    {
      claim_id: "CLM-1022",
      status: "in_progress",
      decision: null,
      payout: null,
    },
    { claim_id: "CLM-1023", status: "waiting", decision: null, payout: null },
  ],
  summary: {
    approved: 2,
    declined: 1,
    referred: 0,
    waiting_for_sign_off: [{ claim_id: "CLM-1008", payout: 2240 }],
    left_for_handler: ["CLM-1018"],
    in_progress: ["CLM-1022"],
    waiting: ["CLM-1023"],
  },
};

function showQueue(run: Run | null, extra: Routes = {}) {
  const routes: Routes = {
    "GET /api/claims": [claimSummary],
    "GET /api/dispatches/latest": run,
    ...extra,
  };
  const fetchMock = stubApi(routes);
  renderAt("/");
  return { routes, fetchMock };
}

const dispatchPanel = () => panel("Dispatch");

it("says when there's no dispatch yet", async () => {
  showQueue(null);
  const found = await dispatchPanel();
  expect(await found.findByText("No dispatch yet.")).toBeDefined();
});

it("starts a dispatch with 3 claim agents unless told otherwise", async () => {
  const { fetchMock } = showQueue(null, {
    "POST /api/dispatches/start": { status: "accepted" },
  });
  const found = await dispatchPanel();
  const agents = found.getByLabelText("Claim agents at once");
  expect((agents as HTMLInputElement).value).toBe("3");
  expect(agents.getAttribute("min")).toBe("1");
  expect(agents.getAttribute("max")).toBe("25");

  fireEvent.change(agents, { target: { value: "25" } });
  fireEvent.click(found.getByRole("button", { name: "Start dispatch" }));
  await vi.waitFor(() => {
    const start = fetchMock.mock.calls.find(
      ([path]) => path === "/api/dispatches/start",
    );
    expect(start?.[1]?.body).toBe(JSON.stringify({ agents: 25 }));
  });
});

it("says why a dispatch didn't start", async () => {
  showQueue(null, {
    "POST /api/dispatches/start": new Refusal(
      503,
      "The agent's service isn't running",
    ),
  });
  const found = await dispatchPanel();
  fireEvent.click(found.getByRole("button", { name: "Start dispatch" }));
  expect((await found.findByRole("alert")).textContent).toBe(
    "The agent's service isn't running",
  );
  const button = found.getByRole("button", { name: "Start dispatch" });
  expect(button.hasAttribute("disabled")).toBe(false);
});

it("shows a running dispatch's claims, cost and time", async () => {
  showQueue(running);
  const found = await dispatchPanel();
  expect(await found.findByText("Running")).toBeDefined();
  expect(found.getByText(/with 3 claim agents at once$/)).toBeDefined();
  expect(found.getByText("$0.0123")).toBeDefined();
  expect(found.getByText("1m 15s")).toBeDefined();
  const items = found.getAllByRole("listitem");
  expect(items.map((item) => item.textContent)).toEqual([
    "DecidedCLM-1001Approved$420.00",
    "In progressCLM-1008",
  ]);
  expect(found.queryByText("Summary")).toBeNull();
});

it("shows the summary when a dispatch finishes, without a reload", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { routes } = showQueue(running);
  const found = await dispatchPanel();
  await found.findByText("Running");

  routes["GET /api/dispatches/latest"] = finished;
  await act(() => vi.advanceTimersByTimeAsync(REFRESH_MS));
  expect(await found.findByText("Finished")).toBeDefined();
  expect(found.getByText(/, finished at /)).toBeDefined();
  expect(found.getByText("52s")).toBeDefined();
  const summary = within(
    found.getByText("Summary").nextElementSibling as HTMLElement,
  );
  expect(
    summary.getByText("2 approved, 1 declined and 0 referred."),
  ).toBeDefined();
  expect(summary.getByText(/Waiting for sign-off/).textContent).toBe(
    "Waiting for sign-off: CLM-1008 $2,240.00",
  );
  expect(summary.getByText(/Left for a handler/).textContent).toBe(
    "Left for a handler: CLM-1018",
  );
  expect(summary.getByText(/Still in progress/).textContent).toBe(
    "Still in progress: CLM-1022",
  );
  expect(summary.getByText(/Not started/).textContent).toBe(
    "Not started: CLM-1023",
  );
  expect(
    summary.getByRole("link", { name: "CLM-1018" }).getAttribute("href"),
  ).toBe("/claims/CLM-1018");
});

it("says when a dispatch has nothing to work", async () => {
  showQueue({ ...finished, claims: [] });
  const found = await dispatchPanel();
  expect(await found.findByText("No claims to work.")).toBeDefined();
});
