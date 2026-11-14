import { expect, test } from "@playwright/test";
import { post, started } from "./api";

// These tests stand in for the agent's service and its claim agents by calling
// the API through the dashboard's proxy. Only this file creates evaluations.

type DecisionKind = "approve" | "decline" | "refer";

interface Scored {
  claim_id: string;
  handler_decision: DecisionKind;
  handler_payout: number;
}

const DECISION_LABELS: Record<DecisionKind, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};
const WRONGFUL_DECLINE = "$1,500.00";
const NEEDLESS_REFERRAL = "$50.00";

// The agent's decision on a copy: the handler's, or a wrong one when asked, with
// what the wrong one costs.
function played(copy: Scored, wrongly: boolean) {
  const wrong: DecisionKind =
    copy.handler_decision === "refer" ? "decline" : "refer";
  const decision = wrongly ? wrong : copy.handler_decision;
  return {
    decision,
    payout: decision === "approve" ? copy.handler_payout : 0,
    mistake: decision === "decline" ? WRONGFUL_DECLINE : NEEDLESS_REFERRAL,
  };
}

test("starting an evaluation reaches the agent's service", async ({
  page,
  request,
}) => {
  await page.goto("/scoreboard");
  await page.getByLabel("Set").selectOption({ label: "Held-out set" });
  await page.getByLabel("Just its five tiny claims").check();
  await page.getByLabel("Claim agents at once").fill("4");
  await page.getByRole("button", { name: "Start evaluation" }).click();
  await expect
    .poll(() => started(request))
    .toContainEqual({
      path: "/api/evaluations",
      body: { agents: 4, eval_set: "held_out", tiny: true },
    });
});

test("the scoreboard shows an evaluation played through the API", async ({
  page,
  request,
}) => {
  const created = await post(request, "/api/evaluations", {
    agents: 3,
    eval_set: "held_out",
    tiny: true,
    model: "openai/gpt-6-luna",
    reasoning_effort: "low",
  });
  const { run_id, number } = (await created.json()) as {
    run_id: string;
    number: number;
  };
  const shown = await request.get(`/api/evaluations/${run_id}`);
  const { claims } = (await shown.json()) as { claims: Scored[] };
  expect(claims).toHaveLength(5);

  for (const [index, copy] of claims.entries()) {
    const { decision, payout } = played(copy, index === 0);
    const claimPath = `/api/claims/${copy.claim_id}`;
    await post(request, `${claimPath}/start`, {
      thread_id: `e2e-${copy.claim_id}`,
    });
    await post(request, `${claimPath}/decision`, {
      decision,
      payout,
      section: "Policy wording",
      reason: "Played by the end-to-end test.",
    });
    await post(request, `${claimPath}/model-calls`, {
      run_id,
      model: "openai/gpt-6-luna",
      input_tokens: 1500,
      output_tokens: 90,
      cost: 0.002,
    });
    await post(request, `${claimPath}/work-times`, { run_id, seconds: 12 });
  }
  await post(request, `/api/runs/${run_id}/finish`, {});

  const [missed] = claims;
  const wrong = played(missed, true);

  await page.goto("/scoreboard");
  const row = page.getByRole("row", {
    name: new RegExp(`Evaluation ${String(number)}`),
  });
  await expect(row).toContainText("Held-out set, tiny claims");
  await expect(row).toContainText("Finished");
  await expect(row).toContainText(wrong.mistake);
  await expect(row).toContainText("$0.0020");
  await expect(row).toContainText("12s");

  await row.getByRole("link").click();
  await expect(page).toHaveURL(`/scoreboard/${run_id}`);
  await expect(page.getByLabel("Decision accuracy: 80%")).toBeVisible();
  const table = page.getByRole("region", { name: "Claims" });
  await expect(table.getByText("Miss", { exact: true })).toHaveCount(1);
  const missedRow = table.getByRole("row", { name: /Miss/ });
  await expect(missedRow).toContainText(missed.claim_id);
  await expect(missedRow).toContainText(
    new RegExp(
      `${DECISION_LABELS[missed.handler_decision]}\\s*\\$[\\d,.]+\\s*${DECISION_LABELS[wrong.decision]}\\s*\\$0\\.00`,
    ),
  );

  await missedRow.getByRole("link", { name: missed.claim_id }).click();
  await expect(page.getByText(/An evaluation's copy of/)).toBeVisible();
});
