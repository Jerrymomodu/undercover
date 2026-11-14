# The claims pilot

From the head of claims operations at UnderCover Travel Insurance.

## How claims work today

UnderCover sells travel insurance on three plans: Economy, Premium and First. Our three claims handlers work through a queue of claims by hand. For each claim, a handler reads the customer's story and documents and checks them against the policy and our policy wording. Then they approve the claim with a payout, decline it or refer it. A claim is referred when it needs someone's judgment or more information, as the claims manual explains.

## The pilot

We want an AI agent, the UnderCover Agent, to work the queue the way a handler does. For each claim it should:

- read the claim, the customer's policy and claim history, and the sections of the policy wording and the claims manual it needs
- approve, decline or refer the claim
- work out the payout when it approves
- explain the decision in two or three sentences, along with the relevant section of the policy

Our goal is to handle claims straight through, as accurately as our handlers do.

## Working the queue on its own

The agent works the queue in dispatches, which a handler starts from the dashboard:

- A dispatch works every claim left in progress and every waiting claim, oldest submitted first, with up to N claim agents working at once. The handler chooses N, from 1 to 25. Code chooses the claims and keeps track of the dispatch, with no model, and only one dispatch or evaluation runs at a time. When it finishes, the dispatch has a summary built from our records. The agent can also work one named claim.
- Each claim goes to a fresh claim agent that works that one claim from a clean start. Every step on a claim is recorded on that claim.
- For each claim the agent looks up the sections of the policy wording and the claims manual it needs, the way a handler would, rather than being handed whole documents. It works out an approval's payout with UnderCover's payout rules, which are part of our systems.
- An approval over the sign-off limit pauses the agent's work on that claim, keeping everything it has worked out, until a handler signs off. As soon as a handler signs off, the agent picks the claim up from where it stopped and pays it, and between the sign-off and the payment the claim shows as in progress. If the agent isn't running at that moment, the next dispatch picks the claim up. The payment records who signed off and when. For now a handler can only sign off.
- Work survives a restart. If the agent is stopped partway through a claim, by a crash, a restart or Ctrl-C, the next dispatch carries on with that claim from where it got to, and that doesn't count as a new attempt. A dispatch that was stopped shows as stopped, and the next dispatch finishes what it left.
- Problems are put right automatically. A claim that hits a rate limit or a timeout waits and carries on from where it got to, as the same attempt, and one that is still hitting them after its waits stays in progress for the next dispatch. A claim that fails with any other error goes back in the queue, and the same dispatch tries it once more; a claim that fails twice is left for a handler. One bad claim never stops the dispatch, and no claim is ever decided or paid twice, even when a step runs again after a restart.
- We record the tokens and the cost of every model call, and the time the agent spends working on each claim, leaving out any wait for a sign-off, each with the dispatch or evaluation it happened in.
- Evaluations check the agent against our handlers' decisions. An evaluation works its own copies of one of our labelled sets, the queue's 25 claims or the 25 held-out claims, whole or just five of them, through the same dispatcher and claim agent as a dispatch. The copies never show in the queue, a dispatch never carries them on, and nobody signs them off: an approval held for sign-off counts as finished.

## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off, decided or left for a handler.
- The latest dispatch: each of its claims and where it stands, its model cost and time, and when it finishes, its summary: how many claims were approved, declined and referred, each payout waiting for a sign-off, and each claim left for a handler or still in progress.
- Each claim in full, with the agent's decision and its reasons.
- What the agent is doing on a claim while it works, step by step, including the sections it read and any attempt that failed.
- The scoreboard: each evaluation, newest first, with how often the agent's decision matches our handlers' and its payout is within a dollar, what its mistakes would cost us, the share of claims it handles straight through, and its model cost and time per claim and for the whole run. Each evaluation opens to its claims, with our handler's decision beside the agent's and the misses easy to spot.
- The claim agent's instructions, read only.

## Rules

- A payout over $1,000 needs a handler's sign-off. The agent can approve such a claim, but the payment waits until a handler signs off. The system must block the payment until then, even if the agent tries to pay.
- Decisions follow the policy wording and the claims manual. The wording comes first, and the manual says how to read it.
- Our handlers' own decisions on these claims are in `data/evals/`. We use them to check the agent's work. The agent must never see them.
- Amounts are in US dollars.

## Our records

Everything is in `data/`, described in `data/README.md`: the claims queue, the policies, the customers, the plans, the handlers, the policy wording and the claims manual. The held-out claims in `data/evals/` are for checking the agent later and stay out of the queue.

## Not for now

- No sign-in. Everyone who uses the screens sees everything.
- No real payments.
- No messages to customers.