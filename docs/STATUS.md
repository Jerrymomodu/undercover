# Status

The pilot from `docs/PLAN.md` is built: all six phases are done.

## What's built

- `backend/`: FastAPI on SQLite. The database is `undercover.db` at the repo root, or the path in `UNDERCOVER_DB`, seeded from `data/` without `data/evals/` or `data/security/`.
  - Read routes for the claims, policies with their plan and add-ons, customers, claim history, the policy wording, the handlers and the agent's instructions, which are read from `backend/instructions.md` on each request.
  - The claim workflow: start, record steps, decide, pay, sign off and release. A claim is `waiting`, `in_progress`, `awaiting_sign_off` or `decided`.
  - The payment rule: a payout over $1,000.00 can't be paid until a handler signs off, and the sign-off makes the payment. A payment must be for exactly the approved payout, once.
  - `POST /api/claims/{claim_id}/run` starts the agent on a waiting claim in the background.
- `agent/`: the UnderCover Agent, `run(claim_id, thread_id)`. It reads its instructions from the API, starts the claim, decides it with six tools over the API (`get_claim`, `get_policy`, `get_claim_history`, `get_policy_wording`, `decide_claim`, `pay_claim`), records each step, and puts the claim back in the queue if the run ends without a decision. It uses `openai/gpt-6-luna` at low reasoning effort, or the model in `MODEL_NAME`.
- `dashboard/`: React in the UnderCover brand, light and dark.
  - The queue (`#/`): counts by status and every claim with its status, decision and payout, refreshed every 3 seconds.
  - The claim page (`#/claims/<id>`): the claim in full, the policy, the customer and their earlier claims, the decision with its reason and policy section, the payment, and the agent's steps, refreshed every second while it works. A waiting claim has "Run the agent"; a claim waiting for sign-off lets a handler sign off and pay.
  - The instructions page (`#/instructions`): the agent's instructions, read only.
- `e2e/`: Playwright tests of the queue, the claim page, live steps, the sign-off path and the instructions. They run their own backend on port 8001 with `e2e/undercover.db`, and their own dashboard on port 5174.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173. The backend seeds the database on startup if the file is missing.
- `npm run seed` rebuilds the database from `data/`, which clears every decision.
- `uv run -m agent CLM-1001` runs the agent on a claim from the terminal, and `uv run -m agent` works every waiting claim. The backend must be running. Each run calls the model.
- `npm run check` runs every check.

## Known limits

- Decisions aren't yet scored against `data/evals/`.
- The agent runs one claim per click; there's no button to work the whole queue from the dashboard.
- Runs aren't durable: if the backend restarts during a run, the claim stays in progress. Run `npm run seed` to reset, or release it with `POST /api/claims/<id>/release`.
