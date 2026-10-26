# Status

The pilot is being built from `docs/PLAN.md`. Phases 1 to 4 of 6 are done.

## Built so far

- `backend/`: SQLite in `undercover.db` at the repo root (or the path in `UNDERCOVER_DB`), seeded from `data/` without `data/evals/` or `data/security/`. Read routes for claims, policies with their plan and add-ons, customers, claim history, the policy wording, the agent's instructions and the handlers.
- The claim workflow in `backend/`: starting a claim, recording steps, deciding, paying, signing off and releasing. A payout over $1,000 can only be paid after a handler signs off, and the sign-off makes the payment.
- `agent/`: the UnderCover Agent. `run(claim_id, thread_id)` reads its instructions from `GET /api/instructions` (read from `backend/instructions.md` on each request), starts the claim, decides it with six tools over the API, records each step, and puts the claim back in the queue if the run ends without a decision.
- `POST /api/claims/{claim_id}/run` starts the agent on a waiting claim in the background.
- `dashboard/`: the UnderCover brand in light and dark mode, the claims queue with counts by status (refreshed every 3 seconds), and the agent's instructions, read only. Pages are chosen by the URL hash: `#/`, `#/claims/<id>` and `#/instructions`. The claim page is a placeholder until Phase 5.
- `e2e/`: one test that the queue lists every claim

## Running it

- `npm run seed` rebuilds the database from `data/`. The backend also seeds it on startup if the file is missing.
- `uv run -m agent CLM-1001` runs the agent on a claim, and `uv run -m agent` works every waiting claim. The backend must be running. This calls the model in `MODEL_NAME`, or `openai/gpt-6-luna`.
- `npm run dev` starts the backend on port 8000 and the dashboard on port 5173.
