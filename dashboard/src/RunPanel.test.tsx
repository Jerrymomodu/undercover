import { act, cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import type { Run } from "./api";
import { App } from "./App";
import { Refusal, stubApi, summary } from "./testing";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const run: Run = {
  run_id: "run-1",
  cap: 5,
  started_at: "2026-10-31T22:00:00+00:00",
  finished_at: null,
  summary: null,
  todos: [],
};

function renderQueue() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
}

function panel() {
  return within(screen.getByRole("region", { name: "This run" }));
}

it("says when there is no run yet", async () => {
  stubApi({ "GET /api/claims": [summary], "GET /api/runs/current": null });
  renderQueue();
  expect(await screen.findByText(/No run yet/)).toBeDefined();
});

it("shows a run before its to-do list is written", async () => {
  stubApi({ "GET /api/claims": [summary], "GET /api/runs/current": run });
  renderQueue();
  expect(
    await screen.findByText(/hasn't written its to-do list/),
  ).toBeDefined();
  expect(panel().getByText("Running")).toBeDefined();
  expect(panel().getByText(/up to 5 claims/)).toBeDefined();
});

it("shows the to-do list with each item's state", async () => {
  stubApi({
    "GET /api/claims": [summary],
    "GET /api/runs/current": {
      ...run,
      cap: null,
      todos: [
        { content: "CLM-1001: trip delay", status: "done" },
        { content: "CLM-1002: baggage", status: "in_progress" },
        { content: "CLM-1003: medical", status: "for_handler" },
        { content: "Write the summary", status: "to_do" },
      ],
    },
  });
  renderQueue();
  const list = await screen.findByRole("list", { name: "To-do list" });
  const items = within(list).getAllByRole("listitem");
  expect(items.map((item) => item.textContent)).toEqual([
    "DoneCLM-1001: trip delay",
    "In progressCLM-1002: baggage",
    "Left for a handlerCLM-1003: medical",
    "To doWrite the summary",
  ]);
  expect(panel().getByText(/whole queue/)).toBeDefined();
});

it("shows a finished run's summary", async () => {
  stubApi({
    "GET /api/claims": [summary],
    "GET /api/runs/current": {
      ...run,
      finished_at: "2026-10-31T22:05:00+00:00",
      summary: "Worked 5 claims.",
      todos: [{ content: "CLM-1001", status: "done" }],
    },
  });
  renderQueue();
  expect(await screen.findByText("Worked 5 claims.")).toBeDefined();
  expect(panel().getByText("Finished")).toBeDefined();
});

it("refreshes as the agent works", async () => {
  vi.useFakeTimers();
  const routes: Record<string, unknown> = {
    "GET /api/claims": [summary],
    "GET /api/runs/current": null,
  };
  stubApi(routes);
  renderQueue();
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(screen.getByText(/No run yet/)).toBeDefined();
  routes["GET /api/runs/current"] = {
    ...run,
    todos: [{ content: "CLM-1001", status: "in_progress" }],
  };
  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(panel().getByText("CLM-1001")).toBeDefined();
});

it("shows an error when the run can't load", async () => {
  stubApi({
    "GET /api/claims": [summary],
    "GET /api/runs/current": new Refusal(500, "The backend is down"),
  });
  renderQueue();
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The backend is down",
  );
});
