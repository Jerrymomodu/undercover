import { type APIRequestContext, expect, test } from "@playwright/test";

// This test stands in for the queue agent by calling the API through the
// dashboard's proxy, and watches the queue page update without a reload.

async function send(
  request: APIRequestContext,
  method: "post" | "put",
  path: string,
  data: object,
) {
  const response = await request[method](path, { data });
  expect(response.ok()).toBe(true);
}

test("the queue page shows the run's to-do list", async ({ page, request }) => {
  await page.goto("/");
  const run = page.getByRole("region", { name: "This run" });
  await expect(run).toBeVisible();

  await send(request, "post", "/api/runs", { run_id: "e2e-run", cap: 2 });
  await send(request, "put", "/api/runs/e2e-run/todos", {
    todos: [
      { content: "CLM-1010: baggage", status: "in_progress" },
      { content: "CLM-1011: medical", status: "to_do" },
    ],
  });
  await expect(run.getByText("Running")).toBeVisible();
  await expect(run.getByText(/up to 2 claims/)).toBeVisible();
  const first = run.getByRole("listitem").filter({ hasText: "CLM-1010" });
  await expect(first.getByText("In progress")).toBeVisible();

  await send(request, "put", "/api/runs/e2e-run/todos", {
    todos: [
      { content: "CLM-1010: baggage", status: "done" },
      { content: "CLM-1011: medical", status: "for_handler" },
    ],
  });
  await send(request, "post", "/api/runs/e2e-run/finish", {
    summary: "Worked 2 claims: 1 approved, 1 left for a handler.",
  });
  await expect(first.getByText("Done")).toBeVisible();
  await expect(
    run.getByRole("listitem").filter({ hasText: "CLM-1011" }),
  ).toContainText("Left for a handler");
  await expect(run.getByText("Finished")).toBeVisible();
  await expect(
    run.getByText("Worked 2 claims: 1 approved, 1 left for a handler."),
  ).toBeVisible();
});
