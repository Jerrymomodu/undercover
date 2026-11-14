import { expect, test } from "@playwright/test";
import { post } from "./api";

// This test stands in for a claim agent by calling the API through the
// dashboard's proxy, on a claim no other test touches.

test("a claim that fails twice is left for a handler", async ({
  page,
  request,
}) => {
  await page.goto("/claims/CLM-1016");
  const heading = page.locator(".claim-heading");
  await expect(heading.getByText("Waiting")).toBeVisible();

  await post(request, "/api/claims/CLM-1016/start", { thread_id: "e2e-3" });
  await post(request, "/api/claims/CLM-1016/steps", {
    kind: "reading",
    content: "Policy wording, section 7: Emergency Medical",
  });
  await post(request, "/api/claims/CLM-1016/failure", {
    reason: "RuntimeError: The model timed out",
  });
  await expect(
    page.getByText("Back in the queue after a failed attempt."),
  ).toBeVisible();

  await post(request, "/api/claims/CLM-1016/start", { thread_id: "e2e-4" });
  await post(request, "/api/claims/CLM-1016/failure", {
    reason: "RuntimeError: The model timed out again",
  });
  await expect(heading.getByText("Left for a handler")).toBeVisible();
  await expect(
    page.getByText(
      "The agent couldn't finish this claim in 2 attempts, so it's left for a handler.",
    ),
  ).toBeVisible();

  const read = page.locator(".sections-read");
  await expect(read.getByRole("listitem")).toHaveText([
    "Policy wording, section 7: Emergency Medical",
  ]);
  const failed = page.locator(".step", { hasText: "Failed" });
  await expect(failed).toHaveText([
    /Failed RuntimeError: The model timed out$/,
    /Failed RuntimeError: The model timed out again$/,
  ]);
});
