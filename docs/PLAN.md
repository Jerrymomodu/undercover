# Plan: the claims pilot

This plan builds the pilot in `docs/SPEC.md`: a backend that holds the claims queue and enforces the rules, the UnderCover Agent that decides claims through the backend's API, and a dashboard where the handlers watch the queue, read each claim and its decision, follow the agent step by step, read its instructions and sign off large payouts.

## The approach

### Where the rules live

The rules that matter most are enforced in the backend, not in the agent's instructions. The agent is told about the $1,000 limit so it can explain itself, but the backend is what blocks a payment until a handler signs off. A model can ignore a prompt; it can't get past a `403`. The same goes for the order of things: a claim can only be decided while the agent is working on it, paid only once approved, and paid only the approved amount.

### Claim statuses

The spec's four states become one `status` column on each claim:

| Status | Label on screen | Color | Set when |
|---|---|---|---|
| `waiting` | Waiting | Cerulean | seeded from `data/claims.json` (`open` there), or a run ends without a decision |
| `in_progress` | In progress | Marigold | the agent starts on the claim |
| `awaiting_sign_off` | Waiting for sign-off | Coral | the agent approves a payout over $1,000 |
| `decided` | Decided | Sea Green | the agent declines or refers, approves $1,000 or less, or a handler signs off |

A referral is a decision, so a referred claim is `decided` with the decision `refer`.

### Paying and signing off

- The agent records its decision with one operation and pays with a separate one that takes the amount, as `docs/TECH_STACK.md` asks.
- Paying succeeds only when the claim is approved, the amount equals the approved payout and the claim hasn't been paid.
- When the payout is over the limit in `data/company.json` ($1,000.00), paying returns `403` with "A payout over $1,000.00 needs a handler's sign-off." until a handler signs off. The handler's sign-off releases the payment itself, so nobody has to pay twice.
- Only a handler with `can_approve_over_limit` can sign off. There's no sign-in in the pilot, so the dashboard asks which handler is signing off.
- Payments are records in the database. No money moves.

### What the agent sees

The agent reaches everything through the backend's API: the claim, the policy with its plan's limits and add-ons, the customer's claim history (not their contact details) and the policy wording. Its instructions are also served by the API, from `backend/instructions.md`, so the dashboard shows exactly what the agent reads. Nothing from `data/evals/`, `data/security/` or the claims manual is loaded into the database, so the agent can't reach it.

### Following the agent step by step

`run(claim_id, thread_id)` streams the agent's progress and posts each step to the backend: each tool it calls with its inputs, what came back, and its final reply. The dashboard polls the claim's steps every second while the claim is in progress. Polling is the simplest thing that works here; nothing about the pilot needs a socket.

`run` also starts the claim (`waiting` to `in_progress`) before the model is called, and if the run ends without a decision, or fails, it puts the claim back to `waiting` with a final step that says so. That keeps a claim from being stuck in progress forever. It's the one place the agent handles an error.

The agent can be started two ways: the "Run the agent" button on a waiting claim, which calls the backend and runs the agent in the background, or `uv run -m agent CLM-1001` from the terminal (with no claim ids it works every waiting claim in turn).

### Data and tests

- SQLite with Python's built-in `sqlite3`; no ORM. Nested parts of a record (a claim's items and documents, a policy's trip and travelers, a customer's claim history) are stored as JSON text in their row, because they're always read with it.
- The database file is `undercover.db` at the repo root (already ignored by git), or the path in `UNDERCOVER_DB`. `npm run seed` rebuilds it from `data/`, and the backend seeds it on startup if it doesn't exist.
- Backend tests use a fresh database in a temporary folder. Agent tests use a stub model and the backend in-process, so no test calls a model.
- The Playwright tests run their own backend on port 8001 with their own database, and their own dashboard on port 5174, so `npm run check` never touches the database you use with `npm run dev`. The tests set up claim states through the API rather than running the agent.

### The API

Every operation has an `operation_id`, a one-line docstring and no optional inputs.

| Method and path | `operation_id` | Used by |
|---|---|---|
| `GET /api/health` | `health` | dashboard |
| `GET /api/claims` | `list_claims` | dashboard |
| `GET /api/claims/{claim_id}` | `get_claim` | agent, dashboard |
| `GET /api/policies/{policy_id}` | `get_policy` | agent, dashboard |
| `GET /api/customers/{customer_id}` | `get_customer` | dashboard |
| `GET /api/customers/{customer_id}/claim-history` | `get_claim_history` | agent |
| `GET /api/policy-wording` | `get_policy_wording` | agent |
| `GET /api/instructions` | `get_instructions` | agent, dashboard |
| `GET /api/handlers` | `list_handlers` | dashboard |
| `POST /api/claims/{claim_id}/start` | `start_claim` | agent's `run` |
| `GET /api/claims/{claim_id}/steps` | `list_steps` | dashboard |
| `POST /api/claims/{claim_id}/steps` | `record_step` | agent's `run` |
| `POST /api/claims/{claim_id}/release` | `release_claim` | agent's `run` |
| `POST /api/claims/{claim_id}/decision` | `decide_claim` | agent |
| `POST /api/claims/{claim_id}/payment` | `pay_claim` | agent |
| `POST /api/claims/{claim_id}/sign-off` | `sign_off_claim` | dashboard |
| `POST /api/claims/{claim_id}/run` | `run_agent` | dashboard |

The agent's tools are `get_claim`, `get_policy`, `get_claim_history`, `get_policy_wording`, `decide_claim` and `pay_claim`. The other operations are for `run` and the dashboard, not for the model.

## Phase 1: The backend's records

Build the database and the read side of the API.

- `backend/db.py`: the schema (claims, policies, customers, plans, add-ons, handlers, settings, documents, decisions, payments, steps) and a connection helper.
- `backend/seed.py`: rebuilds the database from `data/claims.json`, `policies.json`, `customers.json`, `plans.json`, `handlers.json`, `company.json` and `policy_wording.md`. Claims seed as `waiting`. `npm run seed` runs it.
- `GET /api/instructions` reads `backend/instructions.md` on each request (a first draft here; Phase 3 writes it properly), so an edit to the file shows at once without reseeding. (Changed in Phase 4: the first version copied the file into the database, where it went stale.)
- The read operations from the table above, each with a Pydantic response model. `get_policy` includes the plan's limits and the details of the policy's add-ons. `list_claims` gives each claim's id, customer name, type, amount claimed, submitted date, status, and the decision and payout once there is one.
- Unknown ids return `404`.

Success criteria:

- [x] `npm run seed` creates `undercover.db` with 25 claims, 50 policies, 49 customers, 3 plans, 3 add-ons and 3 handlers, all claims `waiting`.
- [x] A test confirms nothing from `data/evals/` or `data/security/` is in the database (for example, no claim CLM-1901 and no table of handler decisions).
- [x] `GET /api/claims` returns 25 claims; `GET /api/claims/CLM-1001` returns its story, three items and four documents.
- [x] `GET /api/policies/POL-2001` returns the Premium plan with a $50.00 deductible and a $300.00 per-item limit.
- [x] `GET /api/customers/CUS-3001/claim-history` returns CLM-0412 and nothing else about the customer.
- [x] `GET /api/policy-wording` returns the wording, version 2026.1, starting "# UnderCover Travel Insurance: Policy Wording".
- [x] `GET /api/claims/CLM-9999` returns `404`.
- [x] Every route in `/openapi.json` has an `operation_id`, a summary and only required inputs (checked by a test).
- [x] `npm run check:python` passes with coverage of 80% or more.

## Phase 2: The claim workflow and the payment rule

Build the operations that change a claim, with the rules in the backend.

- `start_claim` takes a `thread_id`, moves a `waiting` claim to `in_progress`, and returns `409` for any other status.
- `record_step` takes a `thread_id`, a `kind` (`tool_call`, `tool_result`, `reply` or `note`) and the `text`; `list_steps` returns the claim's steps in order.
- `decide_claim` takes `decision` (`approve`, `decline` or `refer`), `payout`, `reason` and `policy_section`. It needs the claim `in_progress`. An approval needs a payout over zero; a decline or referral needs a payout of zero. An approval over the limit moves the claim to `awaiting_sign_off`; everything else moves it to `decided`.
- `pay_claim` takes `amount`, and pays only an approved, unpaid claim, at exactly the approved payout. Over the limit without a sign-off, it returns `403` and the claim stays `awaiting_sign_off`.
- `sign_off_claim` takes `handler_id`, needs the claim `awaiting_sign_off` and a handler who can approve over the limit, records the sign-off, makes the payment and moves the claim to `decided`.
- `release_claim` moves an `in_progress` claim back to `waiting`.
- `get_claim` now includes the decision, the payment and the sign-off.

Success criteria:

- [x] Tests walk a claim through each path: decline, refer, approve and pay at $1,000 or less, and approve over $1,000, blocked payment, sign-off, paid.
- [x] Approving a claim at $1,250.00 and then calling `pay_claim` with 1250 returns `403` with "A payout over $1,000.00 needs a handler's sign-off.", records no payment, and leaves the claim `awaiting_sign_off`.
- [x] Approving at exactly $1,000.00 moves the claim to `decided`, and `pay_claim` with 1000 succeeds.
- [x] `pay_claim` returns `409` for a wrong amount, a second payment, or a claim that was declined or referred.
- [x] `decide_claim` returns `409` on a claim that isn't in progress, and `422` for an approval of zero or a decline with a payout.
- [x] `sign_off_claim` returns `404` for an unknown handler and `409` for a claim that isn't waiting for sign-off; afterwards the claim shows the handler's name and the payment.
- [x] `start_claim` on a claim already in progress returns `409`.
- [x] `npm run check:python` passes with coverage of 80% or more.

## Phase 3: The UnderCover Agent

Build the agent on the skeleton's `create_agent` setup.

- `backend/instructions.md`: the agent's instructions. Read the claim, the policy and plan, the claim history and the policy wording; check the claim against the wording (cover, dates, exclusions, waiting periods, limits, per-item limits and add-ons); work out the payout as section 10 of the wording describes, including the deductible; decide; give the reason in two or three sentences and the section it rests on; and pay an approval. It says a valid claim over $1,000 is still an approval, and that its payment waits for a handler. The instructions are written from the policy wording alone, not from `data/evals/` or the claims manual.
- `agent/main.py`: the six tools over the API, each returning the backend's reply to the model, including a refusal such as the `403`, so the agent can see and report a blocked payment. `run(claim_id, thread_id)` fetches the instructions from the API, starts the claim, streams the agent and records each step, and releases the claim if it ends without a decision. The model stays `openai/gpt-6-luna` at low reasoning effort, or `MODEL_NAME`.
- `agent/__main__.py`: `uv run -m agent CLM-1001 CLM-1002` runs those claims; `uv run -m agent` works every waiting claim.
- `run_agent` in the backend: starts `run` in the background with a new thread id and returns the thread id.

Success criteria:

- [x] A stub-model test runs a claim through the tools to a decline and checks the claim is `decided` with the reason and section, and that its steps include each tool call and the final reply.
- [x] A stub-model test approves $1,250.00, has the agent call `pay_claim`, and checks the tool reply contains the `403` message, no payment exists and the claim is `awaiting_sign_off`.
- [x] A stub-model test that ends without a decision leaves the claim `waiting`, with a last step that says the run ended without a decision.
- [x] A test confirms the system prompt the agent uses is the text `GET /api/instructions` returns.
- [x] `POST /api/claims/CLM-1001/run` returns a thread id and starts the agent (tested with `run` replaced by a stub).
- [x] The CLI runs the claims it's given (tested with `run` replaced by a stub).
- [x] `npm run check:python` passes with coverage of 80% or more.

## Phase 4: The dashboard shell, the queue and the instructions

Build the dashboard's frame and two of its pages, in the UnderCover brand.

- The brand from `docs/BRAND.md`: Instrument Sans, Instrument Serif and JetBrains Mono from Google Fonts; the colors as CSS variables; light and dark mode from the system setting; rounded panels with no outline.
- A header with the UnderCover name and links to the queue and the instructions. Pages are chosen by the URL hash (`#/`, `#/claims/CLM-1001`, `#/instructions`), which needs no router library.
- A small typed API client, with types for each response.
- The queue: a count of claims in each status, and a table of every claim with its id, customer, type, amount claimed, submitted date, a status badge, and the decision and payout once decided. Each row opens the claim. The table refreshes every few seconds so runs show up as they happen.
- The instructions page: the agent's instructions, as text, labeled read only.

Success criteria:

- [x] Vitest tests, with `fetch` stubbed, cover the queue (rows, counts, status labels, money as $1,250.00) and the instructions page.
- [x] In the browser with the Playwright MCP server, after `npm run dev`: the queue shows 25 claims, all Waiting, in the brand fonts and colors; clicking a row opens `#/claims/<id>`; the instructions page shows the text from `backend/instructions.md`.
- [x] The same pages read well in dark mode (checked with the Playwright MCP server's dark color scheme).
- [x] `npm run check:ts` passes with coverage of 80% or more.

## Phase 5: The claim page

Build the page that shows one claim in full.

- The claim: summary, story, incident date and place, the items with their amounts, and each document's text.
- The policy: plan, add-ons, trip dates, trip cost and travelers; the customer and their claim history.
- The decision: approve, decline or refer, the payout, the reason and the policy section, and the payment: paid, waiting for sign-off, or not paid.
- The agent's steps, in order, refreshed every second while the claim is in progress.
- "Run the agent" on a waiting claim.
- On a claim waiting for sign-off: a choice of handler and a "Sign off" button, which pays the claim and shows who signed off.

Success criteria:

- [x] Vitest tests, with `fetch` stubbed, cover a waiting claim with its run button, a claim in progress with its steps, a decided claim with its decision and payment, and the sign-off.
- [x] In the browser with the Playwright MCP server: CLM-1001 shows its story, three items and four documents, the Premium policy and the customer's earlier claim; after setting up an approval of $1,250.00 through the API, the page shows Waiting for sign-off, and signing off as Dana Whitfield shows the claim Decided and paid $1,250.00.
- [x] `npm run check:ts` passes with coverage of 80% or more.

## Phase 6: End-to-end tests and a real run

Check the whole product together, then run the real agent on a few claims.

- `playwright.config.ts`: a backend on port 8001 with its own database, seeded fresh each run, and a dashboard on port 5174 pointed at it. `dashboard/vite.config.ts` reads the backend port from `BACKEND_PORT`, defaulting to 8000.
- Playwright tests: the queue lists 25 claims; a claim page shows the claim in full; steps posted through the API appear on the claim page; the over-limit path, from approval to blocked payment to sign-off to paid; the instructions page.
- `README.md` sections for the backend, agent and dashboard stay short; `docs/STATUS.md` says what's built and how to run it.
- A real run, which calls the model: from the dashboard, run the agent on three claims, including one with more than $1,000 claimed. This costs a few cents on `openai/gpt-6-luna`, or nothing with `MODEL_NAME=openrouter/free`. The decisions aren't scored against `data/evals/`; that's for a later day.

Success criteria:

- [ ] `npm run e2e` passes, and running it while `npm run dev` is up leaves the dev database unchanged.
- [ ] In the browser with the Playwright MCP server, a real run shows the agent's steps appearing while it works, then a decision with a two-or-three-sentence reason and a policy section.
- [ ] If the agent approves a payout over $1,000, the claim shows Waiting for sign-off and the steps show its payment was blocked.
- [ ] `npm run check` passes in full.
- [ ] `docs/STATUS.md` describes the pilot and how to run it.

## Not in this plan

From the spec's "Not for now": the claims manual, sign-in, real payments and messages to customers. Also left for later days: scoring the agent against `data/evals/`, the agent's harness and middleware, durable state and checkpoints, and the security claim in `data/security/`.
