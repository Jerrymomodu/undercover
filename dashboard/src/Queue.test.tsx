import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Queue } from "./Queue";
import { stubApi, summary } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const CLAIMS = [
  summary({}),
  summary({
    claim_id: "CLM-1002",
    customer_name: "Tom Reyes",
    claim_type: "baggage",
    amount_claimed: 1480,
    status: "awaiting_sign_off",
    decision: "approve",
    payout: 1250,
  }),
  summary({
    claim_id: "CLM-1003",
    status: "decided",
    decision: "decline",
    payout: 0,
  }),
  summary({ claim_id: "CLM-1004", status: "in_progress" }),
];

it("lists each claim with where it stands", async () => {
  stubApi({ "GET /api/claims": CLAIMS });
  render(<Queue />);
  const link = await screen.findByRole("link", { name: "CLM-1002" });
  expect(link.getAttribute("href")).toBe("#/claims/CLM-1002");

  const row = link.closest("tr");
  if (!row) throw new Error("The claim has no row");
  const cells = within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
  expect(cells).toEqual([
    "CLM-1002",
    "Tom Reyes",
    "Baggage",
    "$1,480.00",
    "Jun 24, 2026",
    "Waiting for sign-off",
    "Approved",
    "$1,250.00",
  ]);
  expect(screen.getByText("Declined")).toBeDefined();
  expect(screen.getAllByText("Trip delay", { selector: "td" })).toHaveLength(3);
});

it("counts the claims in each status", async () => {
  stubApi({ "GET /api/claims": CLAIMS });
  render(<Queue />);
  const counts = await screen.findByRole("list", { name: "Claims by status" });
  expect(
    within(counts)
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).toEqual(["1Waiting", "1In progress", "1Waiting for sign-off", "1Decided"]);
});

it("says when the queue can't be loaded", async () => {
  stubApi({});
  render(<Queue />);
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Couldn't load the queue: No GET /api/claims",
  );
});
