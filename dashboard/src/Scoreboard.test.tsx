import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Evaluation, EvaluationDetail, Run } from "./api";
import { Refusal, panel, renderAt, stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const run: Run = {
  run_id: "run-9",
  number: 9,
  kind: "evaluation",
  agents: 25,
  status: "finished",
  started_at: "2026-11-14T17:02:13+00:00",
  finished_at: "2026-11-14T17:03:01+00:00",
  eval_set: "held_out",
  tiny: true,
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
  claims: [],
  summary: {
    approved: 3,
    declined: 1,
    referred: 1,
    waiting_for_sign_off: [],
    left_for_handler: [],
    in_progress: [],
    waiting: [],
  },
  cost: 0.0215,
  agent_seconds: 160,
};

const finished: Evaluation = {
  run,
  measures: {
    decision_accuracy: 0.8,
    accuracy: 0.6,
    cost_of_mistakes: 1540,
    straight_through: 0.8,
    cost_per_claim: 0.0043,
    seconds_per_claim: 32,
    run_seconds: 48,
  },
};

const running: Evaluation = {
  run: { ...run, run_id: "run-10", status: "running", finished_at: null },
  measures: { ...finished.measures, run_seconds: null },
};

const detail: EvaluationDetail = {
  ...finished,
  claims: [
    {
      claim_id: "E9-CLM-1101",
      copy_of: "CLM-1101",
      handler_decision: "approve",
      handler_payout: 580,
      decision: "approve",
      payout: 580,
      reason: "Weather canceled the flight.",
      agent_decision: "approve",
      right: true,
      mistake_cost: 0,
      cost: 0.004,
      seconds: 30,
    },
    {
      claim_id: "E9-CLM-1104",
      copy_of: "CLM-1104",
      handler_decision: "approve",
      handler_payout: 900,
      decision: "decline",
      payout: 0,
      reason: "Excluded activity.",
      agent_decision: "decline",
      right: false,
      mistake_cost: 1500,
      cost: 0.005,
      seconds: 41,
    },
    {
      claim_id: "E9-CLM-1107",
      copy_of: "CLM-1107",
      handler_decision: "refer",
      handler_payout: 0,
      decision: null,
      payout: null,
      reason: null,
      agent_decision: "refer",
      right: true,
      mistake_cost: 0,
      cost: 0.001,
      seconds: 9,
    },
  ],
};

it("starts an evaluation of a set, whole or tiny, with N claim agents", async () => {
  const fetchMock = stubApi({
    "GET /api/evaluations": [],
    "POST /api/evaluations/start": { status: "accepted" },
  });
  renderAt("/scoreboard");
  const start = await panel("Start an evaluation");
  expect(await screen.findByText("No evaluations yet.")).toBeDefined();

  fireEvent.change(start.getByLabelText("Set"), {
    target: { value: "held_out" },
  });
  fireEvent.click(start.getByLabelText("Just its five tiny claims"));
  fireEvent.change(start.getByLabelText("Claim agents at once"), {
    target: { value: "5" },
  });
  fireEvent.click(start.getByRole("button", { name: "Start evaluation" }));
  await vi.waitFor(() => {
    const sent = fetchMock.mock.calls.find(
      ([path]) => path === "/api/evaluations/start",
    );
    expect(sent?.[1]?.body).toBe(
      JSON.stringify({ agents: 5, eval_set: "held_out", tiny: true }),
    );
  });
});

it("says why an evaluation didn't start", async () => {
  stubApi({
    "GET /api/evaluations": [],
    "POST /api/evaluations/start": new Refusal(
      409,
      "A dispatch or evaluation is already running",
    ),
  });
  renderAt("/scoreboard");
  const start = await panel("Start an evaluation");
  fireEvent.click(start.getByRole("button", { name: "Start evaluation" }));
  expect((await start.findByRole("alert")).textContent).toBe(
    "A dispatch or evaluation is already running",
  );
});

it("lists the evaluations, newest first, with every measure", async () => {
  stubApi({ "GET /api/evaluations": [running, finished] });
  renderAt("/scoreboard");
  const table = await panel("Evaluations");
  const rows = await table.findAllByRole("row");
  expect(within(rows[0]).getByText("Time per claim")).toBeDefined();
  expect(within(rows[1]).getByText("Running")).toBeDefined();
  expect(within(rows[1]).getByText("Not finished")).toBeDefined();
  const done = within(rows[2]);
  expect(done.getByText("Finished")).toBeDefined();
  expect(done.getByText("Held-out set, tiny claims")).toBeDefined();
  expect(done.getByText("Nov 14, 5:02 PM")).toBeDefined();
  expect(done.getByText("openai/gpt-6-luna")).toBeDefined();
  for (const value of ["80%", "60%", "$1,540.00", "$0.0043", "32s", "48s"])
    expect(done.getAllByText(value).length).toBeGreaterThan(0);
  const link = done.getByRole("link", { name: "Evaluation 9" });
  expect(link.getAttribute("href")).toBe("/scoreboard/run-9");
});

it("shows an evaluation's claims beside the handlers' decisions", async () => {
  stubApi({ "GET /api/evaluations/run-9": detail });
  renderAt("/scoreboard/run-9");
  const measures = await panel("Measures");
  expect(measures.getByLabelText("Decision accuracy: 80%")).toBeDefined();
  expect(measures.getByLabelText("Whole run: 48s")).toBeDefined();

  const rows = (await panel("Claims")).getAllByRole("row").slice(1);
  expect(rows.map((row) => row.textContent)).toEqual([
    "E9-CLM-1101Approved $580.00Approved $580.00$0.00$0.004030sWeather canceled the flight.",
    "E9-CLM-1104MissApproved $900.00Declined $0.00$1,500.00$0.005041sExcluded activity.",
    "E9-CLM-1107Referred $0.00Undecided$0.00$0.00109s",
  ]);
  expect(
    within(rows[1])
      .getByRole("link", { name: "E9-CLM-1104" })
      .getAttribute("href"),
  ).toBe("/claims/E9-CLM-1104");
});

it("says when an evaluation doesn't exist", async () => {
  stubApi({});
  renderAt("/scoreboard/nowhere");
  expect(await screen.findByText("Evaluation not found")).toBeDefined();
});

it("links to the scoreboard from the header", async () => {
  stubApi({ "GET /api/claims": [], "GET /api/dispatches/latest": null });
  renderAt("/");
  const link = await screen.findByRole("link", { name: "Scoreboard" });
  expect(link.getAttribute("href")).toBe("/scoreboard");
});

it("marks no misses on copies a running evaluation hasn't reached", async () => {
  const claims = detail.claims.map((claim) => ({
    ...claim,
    decision: null,
    payout: null,
    reason: null,
    agent_decision: "refer" as const,
    right: claim.handler_decision === "refer",
  }));
  stubApi({
    "GET /api/evaluations/run-10": { ...running, claims },
  });
  renderAt("/scoreboard/run-10");
  expect(
    await screen.findByRole("heading", {
      name: "Evaluation 9: Held-out set, tiny claims",
    }),
  ).toBeDefined();
  const table = await panel("Claims");
  expect(table.getAllByText("Undecided")).toHaveLength(3);
  expect(table.queryByText("Miss")).toBeNull();
});
