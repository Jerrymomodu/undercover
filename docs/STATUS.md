# Status

The pilot is being built from `docs/PLAN.md`. Phases 1 and 2 of 6 are done.

## Built so far

- `backend/`: SQLite in `undercover.db` at the repo root (or the path in `UNDERCOVER_DB`), seeded from `data/` without `data/evals/` or `data/security/`. Read routes for claims, policies with their plan and add-ons, customers, claim history, the policy wording, the agent's instructions and the handlers.
- The claim workflow in `backend/`: starting a claim, recording steps, deciding, paying, signing off and releasing. A payout over $1,000 can only be paid after a handler signs off, and the sign-off makes the payment.
- `agent/`: the skeleton's entry point `run(claim_id, thread_id)`, with one tool that calls the health route
- `dashboard/`: the skeleton's page that shows whether the backend is up
- `e2e/`: one test of that page

## Running it

- `npm run seed` rebuilds the database from `data/`. The backend also seeds it on startup if the file is missing.
- `npm run dev` starts the backend on port 8000 and the dashboard on port 5173.
