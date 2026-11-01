# Status

The claims pilot in `docs/PLAN.md` and the agent's harness in `docs/PLAN_HARNESS.md` are built.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173. After changing backend code, restart it if the backend keeps serving the old code: on this Windows machine uvicorn's reload has twice gone stale.
- `uv run -m backend.seed` rebuilds the database from `data/`, putting every claim back in the queue.
- `uv run -m agent --cap 5` runs the agent on at most five waiting claims, leaving the rest waiting. `uv run -m agent` works the whole queue, and `uv run -m agent CLM-1001` works one claim. Each claim's line is printed as it finishes, then the run's summary. All use the real model through OpenRouter, so reseed first and cap a trial at five claims.

## Built

- `backend/`: SQLite database seeded from `data/` (never `data/evals/`), at `undercover.db` or the path in `UNDERCOVER_DB`, created on startup when missing. Read operations: `health`, `list_claims`, `get_claim`, `get_policy`, `get_claim_history`, `list_handlers`, `list_steps`, `get_instructions`, `list_sections`, `read_section` and `get_current_run`. Workflow operations: `start_claim`, `record_step`, `record_decision`, `pay_claim`, `sign_off_claim`, `release_claim`, `start_run`, `write_todos` and `finish_run`.
  - A claim moves from waiting to in progress to decided, or to waiting for sign-off when an approval pays over the limit in `company.json`. `pay_claim` refuses such a payout with a 403 until a handler signs off.
  - `release_claim` puts an undecided claim in progress back to waiting with an `error` step; at its second failure it is left for a handler.
  - The policy wording and the claims manual are split into sections at their `##` headings (13 and 15 sections, each with the intro as section 0).
  - A run has a cap (or none), a to-do list that is replaced as a whole, and a summary. `get_current_run` returns the latest run, or `null` before the first.
  - The agent's instructions are in `backend/instructions/queue.md` and `claim.md`, written from the wording and the manual. A test checks that every operation follows the API rules.
- `agent/`: two agents built with `create_agent`, on `deepseek/deepseek-v4.1-flash` with low reasoning effort unless `MODEL_NAME` is set. It calls the backend at `127.0.0.1`, since `localhost` costs 2 seconds a request on Windows.
  - The queue agent (`agent/queue.py`) has `list_claims`, `write_todos`, `work_claim` and `finish_run`. The harness enforces the cap, refuses to finish while a waiting claim within the cap is missed, marks items still in progress done when the run finishes, releases claims an earlier run left in progress, and finishes the run with a note if the agent fails or stops.
  - `work_claim` (`agent/main.py`) runs a fresh claim agent with `get_claim`, `get_policy`, `get_claim_history`, `list_sections`, `read_section`, `record_decision` and `pay_claim`, records every step on the claim (with a `reading` step for each section read), and reports back in one line. Any failure, or an agent that ends without a decision, releases the claim.
  - Middleware retries a failed model call 3 times (120 second timeout) and a tool call that can't reach the backend, and stops a claim agent after 30 model calls.
- `dashboard/`: the queue (`/`), with counts in five states and a "This run" panel showing the current run's to-do list and summary. A claim in full (`/claims/:claimId`), with its policy, earlier claims, the decision and payment, what the agent read, the agent's steps as it works (readings in Cerulean, failures in Raspberry), a sign-off form for a held payout, and a note when a claim is left for a handler. The agent's instructions (`/instructions`) for running the queue and working a claim, read only. Pages refresh every two seconds. Styled to `BRAND.md` in light and dark mode.
- `e2e/`: tests of the three pages, the agent's steps, signing off a held payout, the run's to-do list filling in and finishing, what the agent read, and a claim left for a handler. Playwright runs its own backend on port 8001 with `e2e/undercover.db`, and its own dashboard on port 5174.

## Last live run

On November 1, 2026, after reseeding, `uv run -m agent --cap 5` with `deepseek/deepseek-v4.1-flash` worked five claims in 3 minutes 23 seconds, oldest submitted first, while the queue page showed the to-do list appear and tick off item by item. CLM-1001 was approved and paid $420.00; CLM-1008 ($2,240.00) and CLM-1011 ($1,150.00) were approved and wait for sign-off; CLM-1018 was referred for a missing proof of value; CLM-1010 was declined under the alcohol exclusion. The other 20 claims stayed waiting and none was left in progress. Each claim read 9 to 12 sections of the wording and the manual. Two things to watch: the agent's run summary misreported CLM-1008 as paid as well as waiting for sign-off, and CLM-1018's referral reason ran to four sentences (the claim instructions were then tightened, not yet tried live). These decisions have not been scored against the handlers' decisions in `data/evals/`.
