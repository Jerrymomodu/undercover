import { expect, test } from "@playwright/test";
import { post, put, started } from "./api";

// These tests stand in for the agent's service and its claim agents by calling
// the API through the dashboard's proxy, on claims no other test touches.

test("starting a dispatch reaches the agent's service with N", async ({
  page,
  request,
}) => {
  await page.goto("/");
  await page.getByLabel("Claim agents at once").fill("5");
  await page.getByRole("button", { name: "Start dispatch" }).click();
  await expect
    .poll(() => started(request))
    .toContainEqual({ path: "/api/dispatches", body: { agents: 5 } });
});

test("the dispatch panel shows its claims, then its summary", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const panel = page.locator("section", {
    has: page.getByRole("heading", { name: "Dispatch" }),
  });

  const response = await post(request, "/api/dispatches", {
    agents: 3,
    model: "openai/gpt-6-luna",
    reasoning_effort: "low",
  });
  const { run_id } = (await response.json()) as { run_id: string };
  await put(request, `/api/runs/${run_id}/claims`, {
    claim_ids: ["CLM-1013", "CLM-1014"],
  });
  const items = panel.getByRole("listitem");
  await expect(panel.getByText("Running", { exact: true })).toBeVisible();
  await expect(items).toHaveText([
    /^Waiting\s*CLM-1013/,
    /^Waiting\s*CLM-1014/,
  ]);

  await post(request, "/api/claims/CLM-1013/start", { thread_id: "e2e-5" });
  await post(request, "/api/claims/CLM-1013/decision", {
    decision: "refer",
    payout: 0,
    section: "Claims manual, section 4",
    reason: "The delay letter is missing.",
  });
  await post(request, "/api/claims/CLM-1013/model-calls", {
    run_id,
    model: "openai/gpt-6-luna",
    input_tokens: 1500,
    output_tokens: 90,
    cost: 0.0042,
  });
  await expect(items.first()).toHaveText(/^Decided\s*CLM-1013\s*Referred/);

  await post(request, `/api/runs/${run_id}/finish`, {});
  await expect(panel.getByText("Finished", { exact: true })).toBeVisible();
  await expect(panel.getByText("$0.0042")).toBeVisible();
  await expect(
    panel.getByText("0 approved, 0 declined and 1 referred."),
  ).toBeVisible();
  await expect(panel.getByText("Not started: CLM-1014")).toBeVisible();

  await items.first().getByRole("link", { name: "CLM-1013" }).click();
  await expect(page).toHaveURL("/claims/CLM-1013");
});
