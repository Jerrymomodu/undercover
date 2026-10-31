import { type APIRequestContext, expect, test } from "@playwright/test";

// These tests stand in for the agent by calling the API through the
// dashboard's proxy, and watch the claim page update without a reload.

async function send(request: APIRequestContext, path: string, data: object) {
  const response = await request.post(path, { data });
  expect(response.ok()).toBe(true);
}

test("the claim page shows what the agent read", async ({ page, request }) => {
  await page.goto("/claims/CLM-1012");
  const read = page.locator("section", {
    has: page.getByRole("heading", { name: "What the agent read" }),
  });
  await expect(read.getByText(/Nothing yet/)).toBeVisible();

  await send(request, "/api/claims/CLM-1012/start", { thread_id: "e2e-3" });
  await send(request, "/api/claims/CLM-1012/steps", {
    kind: "reading",
    content: "Claims manual, section 9: Repeat claims",
  });
  await expect(
    read.getByText("Claims manual, section 9: Repeat claims"),
  ).toBeVisible();
});

test("a claim that fails twice is left for a handler", async ({
  page,
  request,
}) => {
  await page.goto("/claims/CLM-1015");
  const heading = page.locator(".claim-heading");
  await expect(heading.getByText("Waiting")).toBeVisible();

  for (const reason of ["The model timed out", "Too many model calls"]) {
    await send(request, "/api/claims/CLM-1015/start", { thread_id: reason });
    await send(request, "/api/claims/CLM-1015/release", { reason });
  }
  await expect(heading.getByText("Left for a handler")).toBeVisible();
  await expect(page.getByText("The model timed out")).toBeVisible();
  await expect(page.getByText("Too many model calls")).toBeVisible();
  const decision = page.locator("section", {
    has: page.getByRole("heading", { name: "Decision" }),
  });
  await expect(decision.getByText(/after 2 tries/)).toBeVisible();
});
