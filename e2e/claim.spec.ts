import { expect, test, type APIRequestContext } from "@playwright/test";

// Each test sets up its own claim through the API, so the tests never run the
// agent and never call a model.

async function start(request: APIRequestContext, claimId: string) {
  const response = await request.post(`/api/claims/${claimId}/start`, {
    data: { thread_id: "e2e" },
  });
  expect(response.ok()).toBe(true);
}

async function step(
  request: APIRequestContext,
  claimId: string,
  kind: string,
  text: string,
) {
  const response = await request.post(`/api/claims/${claimId}/steps`, {
    data: { thread_id: "e2e", kind, text },
  });
  expect(response.ok()).toBe(true);
}

async function decide(
  request: APIRequestContext,
  claimId: string,
  decision: string,
  payout: number,
) {
  return request.post(`/api/claims/${claimId}/decision`, {
    data: {
      decision,
      payout,
      reason: "The reason for the decision.",
      policy_section: "5. Baggage and Personal Effects",
    },
  });
}

test("a claim is shown in full", async ({ page }) => {
  await page.goto("/#/claims/CLM-1001");
  await expect(page.getByText(/My flight home from Rome/)).toBeVisible();
  await expect(page.locator(".items tbody tr")).toHaveCount(3);
  await expect(page.locator(".document")).toHaveCount(4);
  await expect(page.getByText("UnderCover Premium")).toBeVisible();
  await expect(page.getByText(/CLM-0412/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run the agent" }),
  ).toBeVisible();
});

test("the agent's steps appear while it works", async ({ page, request }) => {
  await start(request, "CLM-1005");
  await page.goto("/#/claims/CLM-1005");
  await expect(page.getByText("The agent is working")).toBeVisible();
  await expect(
    page.getByText("The agent started work on the claim."),
  ).toBeVisible();

  await step(
    request,
    "CLM-1005",
    "tool_call",
    'get_claim {"claim_id": "CLM-1005"}',
  );
  await expect(
    page.getByText('get_claim {"claim_id": "CLM-1005"}'),
  ).toBeVisible();

  expect((await decide(request, "CLM-1005", "decline", 0)).ok()).toBe(true);
  await step(request, "CLM-1005", "reply", "I declined the claim.");
  await expect(page.getByText("Declined", { exact: true })).toBeVisible();
  await expect(page.getByText("I declined the claim.")).toBeVisible();
  await expect(page.getByText("The agent is working")).toBeHidden();
});

test("a payout over $1,000 waits for a handler's sign-off", async ({
  page,
  request,
}) => {
  await start(request, "CLM-1012");
  expect((await decide(request, "CLM-1012", "approve", 1250)).ok()).toBe(true);
  const payment = await request.post("/api/claims/CLM-1012/payment", {
    data: { amount: 1250 },
  });
  expect(payment.status()).toBe(403);

  await page.goto("/#/claims/CLM-1012");
  await expect(page.getByText("Waiting for sign-off")).toBeVisible();
  await expect(page.getByText("Approved $1,250.00")).toBeVisible();
  await page.getByLabel("Handler").selectOption({ label: "Dana Whitfield" });
  await page
    .getByRole("button", { name: "Sign off and pay $1,250.00" })
    .click();
  await expect(
    page.getByText("Paid $1,250.00", { exact: false }),
  ).toContainText("signed off by Dana Whitfield");

  await page.getByRole("link", { name: "Back to the queue" }).click();
  await expect(page.getByRole("row", { name: /CLM-1012/ })).toContainText(
    "Decided",
  );
});
