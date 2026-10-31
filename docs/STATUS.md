# Status

The claims pilot in `docs/PLAN.md` is built: all six phases are done.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173.
- `uv run -m backend.seed` rebuilds the database from `data/`, putting every claim back in the queue.
- `uv run -m agent` works every waiting claim in queue order and prints each decision, then a count. `uv run -m agent CLM-1001` works one claim. Both use the real model through OpenRouter.

## Built

- `backend/`: SQLite database seeded from `data/` (never `data/evals/`), at `undercover.db` or the path in `UNDERCOVER_DB`, created on startup when missing. Read operations: `health`, `list_claims`, `get_claim`, `get_policy`, `get_claim_history`, `list_handlers`, `list_steps`, `get_instructions`. Workflow operations: `start_claim`, `record_step`, `record_decision`, `pay_claim`, `sign_off_claim`. A claim moves from waiting to in progress to decided, or to waiting for sign-off when an approval pays over the limit in `company.json`. `pay_claim` refuses such a payout with a 403 until a handler signs off, and signing off pays it. The agent's instructions are in `backend/instructions.md`, and `get_instructions` serves them followed by the policy wording. A test checks that every operation follows the API rules.
- `agent/`: `run(claim_id, thread_id)` starts the claim, fetches its instructions from the backend and works the claim with five tools named after backend operations: `get_claim`, `get_policy`, `get_claim_history`, `record_decision` and `pay_claim`. It records every tool call, tool result and message as a step. `work_queue()` runs it on each waiting claim, and reports a failed claim and moves on.
- `dashboard/`: the queue (`/`), with counts by state and a line per claim. A claim in full (`/claims/:claimId`), with its policy, earlier claims, the decision and payment, the agent's steps as it works, and a sign-off form for a held payout. The agent's instructions (`/instructions`), read only. The queue and a claim page refresh every two seconds. Styled to `BRAND.md` in light and dark mode.
- `e2e/`: tests of the three pages, the agent's steps appearing on a claim page, and a handler signing off a held payout. Playwright runs its own backend on port 8001 with `e2e/undercover.db`, and its own dashboard on port 5174, so it can run next to `npm run dev`.

## Last live run

On September 27, 2026, `uv run -m agent` with `openai/gpt-6-luna` worked all 25 claims in 2 minutes 47 seconds: 17 approve, 5 decline and 3 refer. Three approvals were over $1,000 and waited for sign-off (CLM-1003, CLM-1008 and CLM-1011), and every other approval was paid its payout. These decisions have not yet been scored against the handlers' decisions in `data/evals/`.

## The harness, in progress

`docs/PLAN_HARNESS.md` is being built.

- Phase 1, done: the backend splits the policy wording and the claims manual into sections (`list_sections`, `read_section`), counts each claim's failed attempts with `release_claim` (the second failure leaves a claim `left_for_handler`), and stores agent runs with their to-do lists (`start_run`, `get_current_run`, `write_todos`, `finish_run`). Steps can now be `reading` or `error`.
- Phase 2, done: the claim agent's instructions are in `backend/instructions/claim.md`, written from the wording and the manual, and `get_instructions` serves them without the wording. The agent looks rules up with `list_sections` and `read_section`, and each section it reads is recorded as a `reading` step. `work_claim` starts a claim, runs a fresh claim agent and reports back in one line, releasing the claim if anything fails. Model calls are retried 3 times with a 120 second timeout, and a claim agent stops after 30 model calls. The default model is `deepseek/deepseek-v4.1-flash`. The agent calls the backend at `127.0.0.1`, since `localhost` costs 2 seconds a request on Windows. A live `uv run -m agent CLM-1001` approved and paid $420.00 in 27 seconds, reading 10 sections.
- Phase 3, done: the queue agent (`agent/queue.py`) works the queue with four tools: `list_claims`, `write_todos`, `work_claim` (a fresh claim agent per claim) and `finish_run`, which refuses while a waiting claim within the cap is missed. The harness enforces the cap, releases claims an earlier run left in progress, and finishes the run with a note if the agent stops. Its instructions are in `backend/instructions/queue.md`; `get_instructions` returns `queue` and `claim`, and the instructions page shows both. `uv run -m agent` works the whole queue, `uv run -m agent --cap 5` at most five claims, and `uv run -m agent CLM-1001` one claim.
