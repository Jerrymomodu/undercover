import { expect, test } from "@playwright/test";

test("the queue lists every claim", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Claims queue" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(25);
});
