# Plan: the agent's harness

This plan builds `docs/HARNESS.md` on top of the finished pilot, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

When it's done, one run of the UnderCover Agent works the whole queue, or as many claims as its cap allows. A queue agent plans the run as a to-do list that the dashboard shows, and hands each claim to a fresh claim agent. The claim agent looks up the sections of the policy wording and the claims manual it needs, and the claim page shows what it read. A claim that fails goes back in the queue, a claim that fails twice is left for a handler, and the queue agent can't finish while it has missed a waiting claim within its cap.

## Design

### The approach in one paragraph

The pilot's Python loop organized the work: it chose the order, fed one claim at a time to the agent and stuffed the whole wording into every prompt. Now the organizing moves into the agent, and the code's job becomes the **harness** around it: the tools it can call, the middleware that wraps each model and tool call, and the instructions it reads. The rule we follow throughout: **the model decides, the harness enforces.** The agent chooses the order and keeps its own to-do list, but the cap, the retry count, "never decide or pay twice" and the check for missed claims are enforced in code and in the backend, where a model can't talk its way past them.

### Two agents, both built with `create_agent`

| | Queue agent | Claim agent (the subagent) |
| --- | --- | --- |
| Job | Plans the run, works through the queue, writes the summary | Works one claim from a clean start |
| Instructions | `backend/instructions/queue.md` | `backend/instructions/claim.md` |
| Tools | `list_claims`, `write_todos`, `work_claim`, `finish_run` | `get_claim`, `get_policy`, `get_claim_history`, `list_sections`, `read_section`, `record_decision`, `pay_claim` |
| Thread | The run id | A new id for every attempt at a claim |
| Sees | One line per claim | One claim, and only the sections it reads |

`work_claim` is how the queue agent hands a claim to a subagent: the tool builds a new claim agent with an empty history, runs it, and returns one line. The queue agent never sees the claim agent's tool calls or documents, so its context grows by one line per claim rather than by a whole claim's work. That is what stops each step getting more expensive as the run goes on. Every step of the claim agent is still recorded on the claim, as in the pilot.

Why not `deepagents`, which already has subagents and a to-do list? The brief asks us to build these pieces into our own agent rather than add another framework, and each piece is small once it's written as a tool. We use LangChain's own middleware where it fits (retries and call limits), since LangChain is already our stack.

### Why our own to-do tool rather than `TodoListMiddleware`

LangChain's `TodoListMiddleware` keeps the list in the agent's memory with three states: pending, in progress and completed. We need a fourth state, left for a handler, and the list has to live in the backend so the dashboard can show it. So `write_todos` is our own tool, named after the backend operation it calls. Like the middleware's tool, it replaces the whole list each time it's called, which keeps it simple: there is no "edit item 3" to get wrong.

| To-do state | Label on screen | Color |
| --- | --- | --- |
| `to_do` | To do | Cerulean |
| `in_progress` | In progress | Marigold |
| `done` | Done | Sea Green |
| `for_handler` | Left for a handler | Raspberry |

### Claim states

The pilot's four states stay, and one is added:

| State | Meaning | Label on screen | Color |
| --- | --- | --- | --- |
| `left_for_handler` | The agent failed on it twice; a handler needs to decide it | Left for a handler | Raspberry |

A claim now moves `waiting` → `in_progress` → `decided` or `waiting_for_sign_off`, as before, or back to `waiting` when an attempt fails, or to `left_for_handler` on the second failure. Raspberry is the brand's fifth color and its alert color, which suits a claim that needs a person.

### The documents as sections

At seed time the backend splits `data/policy_wording.md` and `data/claims_manual.md` at their `## ` headings into a `sections` table: document, number, title and text. The text before the first heading, which holds the document's version, is section 0. That gives 13 sections of the wording (0 to 12) and 15 of the manual (0 to 14).

The claim agent gets two tools: `list_sections(document)` returns the numbers and titles, like a table of contents, and `read_section(document, number)` returns one section. This is how a handler uses a manual: look at the contents, turn to the page you need. It also keeps prompts small as the manual grows.

To show what the agent read, the harness records an extra step of a new kind, `reading`, whenever `read_section` succeeds, such as `Claims manual, section 9: Repeat claims`. The claim page lists these in a "What the agent read" panel, so a handler can see at a glance which rules the decision rests on, without opening every tool result.

### Recovering from problems

Problems are handled at three levels, from the smallest to the largest:

1. **One call.** LangChain's `ModelRetryMiddleware` retries a failed model call 3 times with backoff, which covers provider errors and timeouts. The model client gets a 120 second timeout so a hung call becomes an error rather than a stall. `ToolRetryMiddleware` retries a tool call that fails to reach the backend (`httpx.TransportError`). A refusal from the backend, such as a 409, is not an error: it goes back to the model as text, as in the pilot. `ModelCallLimitMiddleware` stops a claim agent that loops, at 30 model calls.
2. **One claim.** `work_claim` catches anything that ends a claim agent's run, and also treats a run that ends without a decision as a failure. Either way it calls the backend's new `release_claim` operation, which records the reason as an `error` step on the claim and adds one to the claim's failure count. On the first failure the claim goes back to `waiting`; on the second it becomes `left_for_handler`. The count lives on the claim, so it carries over between runs. One bad claim never stops the run.
3. **The whole run.** If the queue agent itself fails, the harness finishes the run with a summary saying it stopped and why. If a whole process is killed mid-claim, the harness releases any claim left in progress with no decision when the next run starts, counting it as a failure. This lives in the harness rather than in `start_run`, so the backend never releases a claim that someone else is working on, such as in the end-to-end tests.

"No claim is ever decided or paid twice" is already enforced by the backend: a decision needs a claim in progress, and a second payment returns 409. `release_claim` only accepts a claim in progress with no decision, so a decided claim can never go back in the queue.

Each failure goes back to the queue agent as a line such as `CLM-1007 failed: model timed out. Back in the queue (1 of 2 tries).` Its instructions tell it to try such claims again once the others are done.

### The cap and the check for missed claims

The harness keeps track of the claims each run has started. Once a run has started as many different claims as its cap, `work_claim` refuses a new one and says so, and the claim stays waiting. Trying a failed claim again doesn't count against the cap. Parallel calls to `work_claim` take a lock and run one after another, so the cap and SQLite are never raced.

`finish_run(summary)` is the queue agent's last tool. Before it records the summary, the harness lists the waiting claims. If any remain and the run is still under its cap, it refuses with their ids, and the agent goes back to work. So the check for missed claims is enforced, not just asked for.

### API

New and changed operations, all following the API rules (an `operation_id`, a one-line docstring, no optional inputs):

| Operation | Route | What it does |
| --- | --- | --- |
| `list_sections` | `GET /api/documents/{document}/sections` | `document` is `policy_wording` or `claims_manual`. The number and title of each section |
| `read_section` | `GET /api/documents/{document}/sections/{number}` | One section: document, number, title and text. 404 for an unknown number |
| `release_claim` | `POST /api/claims/{claim_id}/release` | Body `{reason}`. Needs a claim in progress with no decision (409). Records an `error` step, adds a failure, and moves the claim to `waiting`, or to `left_for_handler` at the second failure |
| `start_run` | `POST /api/runs` | Body `{run_id, cap}`, where `cap` is a number of claims or `null` for the whole queue. 409 for a run id already used |
| `get_current_run` | `GET /api/runs/current` | The latest run with its to-do list, or `null` before the first run. It returns `null` rather than 404 so the dashboard keeps refreshing until a run starts |
| `write_todos` | `PUT /api/runs/{run_id}/todos` | Body `{todos: [{content, status}]}`. Replaces the run's list. 409 once the run has finished |
| `finish_run` | `POST /api/runs/{run_id}/finish` | Body `{summary}`. Records the summary and the time. 409 if already finished |
| `get_instructions` | `GET /api/instructions` | Changed: `{queue, claim}`, the two sets of instructions, without the policy wording |

`get_claim` and `list_claims` gain the `failures` count. Step kinds gain `reading` and `error`. The limit of two tries is a constant in the backend.

### Instructions

`backend/instructions.md` becomes two files, both written from the policy wording and the claims manual, never from `data/evals/`:

- **`queue.md`**: list the waiting claims; write a to-do list with one item per claim, oldest submitted first, plus "Check for missed claims" and "Write the summary"; mark an item in progress before handing it over and done or left for a handler after; work one claim at a time; try a claim that went back in the queue again after the others; stop starting claims when the cap is reached; finish with a summary of three or four sentences for the handlers, with counts and the claims that need a person.
- **`claim.md`**: the pilot's workflow, now in the manual's order (its section 4), and told to find rules with `list_sections` and `read_section` rather than from memory. Always read the wording's section 1 (the plan's limits) and the benefit's section, and look in the manual for what the wording leaves open. It names the manual's rules that change decisions: refer a third claim within 12 months (section 9), treat wild animals as accidental loss (section 7), pay meals without receipts at the flat rate (section 10), refer for a missing document (section 5), and refer when the story and the documents disagree (section 8). The rules for recording the decision and paying stay as they are. It doesn't ask for letters to customers, which are still out of scope.

### The model

The default becomes `deepseek/deepseek-v4.1-flash` with low reasoning effort. `MODEL_NAME` still overrides it, as before, and both agents use the same model.

### Running it

- `uv run -m agent` works the whole queue.
- `uv run -m agent --cap 5` works at most five claims and leaves the rest waiting.
- `uv run -m agent CLM-1001` works one claim with a claim agent, through the same `work_claim` path, so it gets the same release on failure.

Each claim's line is printed as it finishes, then the summary.

### Dashboard

- **Queue page.** A "This run" panel above the table: when it started, its cap ("Up to 5 claims" or "Whole queue"), Running or Finished, the to-do list with a chip for each item's state, and the summary once it's finished. "No run yet" before the first run. It refreshes with the queue every two seconds. A fifth tile counts Left for a handler.
- **Claim page.** A "What the agent read" panel listing the `reading` steps in order. The step list shows `reading` and `error` steps, with errors in Raspberry. A claim left for a handler says so in the decision panel, with the number of tries.
- **Instructions page.** Two panels: "Running the queue" and "Working a claim", still read only.

### How the criteria are checked

As for the pilot: API calls against `npm run dev` on a freshly seeded database, pages in the browser with the Playwright MCP server at `http://localhost:5173`, and tests that never call a model. Stub model tests script the queue agent and the claim agents separately; tests of failures stand in a claim agent that raises. Retry delays are set to zero in tests. Criteria marked "Live" use the real model. Every live run starts with `uv run -m backend.seed` and works at most five claims.

## Phase 1: The backend: sections, release, runs and to-dos

Add the `sections` table and seeding, `list_sections` and `read_section`, the `failures` count and `left_for_handler` state with `release_claim`, the `runs` and `todos` tables with `start_run`, `get_current_run`, `write_todos` and `finish_run`, and the `reading` and `error` step kinds.

- [x] pytest covers every new operation and each of its refusals
- [x] `curl -s localhost:8000/api/documents/policy_wording/sections` returns 13 sections numbered 0 to 12, the second being `1`, "Your plan"; `claims_manual` returns 15 numbered 0 to 14
- [x] `curl -s localhost:8000/api/documents/claims_manual/sections/9` returns the title "Repeat claims" and text containing "third claim within any 12 month period"
- [x] An unknown section number returns 404 and an unknown document returns 422
- [x] Walked through with curl on `CLM-1005`: start, then `release_claim` with a reason gives `waiting`, `failures` 1 and an `error` step with the reason. Start and release again gives `left_for_handler` and `failures` 2. `start_claim` then returns 409
- [x] `release_claim` on a waiting claim, a decided claim and a claim waiting for sign-off each return 409, and the claim is unchanged
- [x] `curl -s localhost:8000/api/runs/current` returns `null` on a fresh database
- [x] `start_run` with cap 5 returns the run with an empty to-do list; `get_current_run` returns it; a second `start_run` with the same id returns 409
- [x] `write_todos` twice replaces the list, keeping the order given. A status of `maybe` or an empty `content` returns 422
- [x] `finish_run` records the summary and finish time; a second `finish_run` and a later `write_todos` each return 409
- [x] The OpenAPI test passes with the new operations
- [x] `grep -rn evals backend agent dashboard/src` finds nothing
- [x] `npm run check` passes

## Phase 2: The claim agent: looking things up and failing safely

Move the instructions to `backend/instructions/claim.md` and rewrite them from the wording and the manual. Add the `list_sections` and `read_section` tools and the `reading` step. Add the retry and call-limit middleware and the model timeout. Build `work_claim`, which starts a claim, runs a fresh claim agent and returns one line, releasing the claim on any failure. Switch the default model. `uv run -m agent CLM-1001` uses `work_claim`.

- [ ] A pytest test checks that the claim agent's tools are exactly `get_claim`, `get_policy`, `get_claim_history`, `list_sections`, `read_section`, `record_decision` and `pay_claim`, each named after a backend operation
- [ ] `curl -s localhost:8000/api/instructions` no longer contains "## 10. How we work out your payment": the wording is looked up, not handed over
- [ ] Stub model test: the stub lists the wording's sections, reads sections 1 and 3, reads manual section 10, then decides and pays. The claim is decided and paid, and has `reading` steps "Policy wording, section 1: Your plan", "Policy wording, section 3: Trip Delay" and "Claims manual, section 10: Meals without receipts" in order
- [ ] Stub model test: reading an unknown section returns the refusal to the model, records no `reading` step, and the run carries on
- [ ] `work_claim` test: a decided claim gives a line like `CLM-1001  approve  $420.00  paid`, and an approval over the limit gives `waiting for sign-off`
- [ ] `work_claim` test: a claim agent that raises leaves the claim `waiting` with `failures` 1 and an `error` step, and the line says it is back in the queue. A second failure leaves it `left_for_handler`, and the line says so
- [ ] `work_claim` test: a claim agent that ends without a decision is released the same way
- [ ] `work_claim` test: a claim that isn't waiting gives a line saying so and changes nothing
- [ ] Stub model test: a model that fails on its first call and succeeds on the retry works the claim with no failure counted
- [ ] Stub model test: a model that never stops calling tools hits the call limit, and the claim is released
- [ ] A test checks the default model is `deepseek/deepseek-v4.1-flash` with low reasoning effort, and that `MODEL_NAME` overrides it
- [ ] `grep -rn "data/" agent` finds nothing: the agent reads nothing from disk
- [ ] Live: after reseeding, `uv run -m agent CLM-1001` prints `CLM-1001  approve  $420.00  paid`, and its steps include `list_sections` and `read_section` calls and at least one `reading` step
- [ ] `npm run check` passes

## Phase 3: The queue agent: the plan, the cap and the finish

Write `backend/instructions/queue.md`. Build the queue agent with `list_claims`, `write_todos`, `work_claim` and `finish_run`, retry middleware and a call limit scaled to the cap, and a recursion limit large enough for a full queue. Add `uv run -m agent` and `--cap`. `get_instructions` returns both sets of instructions, and the instructions page shows them. Remove the pilot's `work_queue` loop.

- [ ] A pytest test checks that the queue agent's tools are exactly `list_claims`, `write_todos`, `work_claim` and `finish_run`
- [ ] Stub model test, a whole run on three waiting claims: the queue agent writes its to-do list, works each claim through a claim agent, ticks each item off and finishes. The backend holds the run with each version of the list as it was written and the summary; the three claims are decided; the output is one line per claim, then the summary
- [ ] Stub model test, the cap: with cap 2 and three waiting claims, a third `work_claim` is refused with a message about the cap, that claim stays `waiting`, and `finish_run` is accepted
- [ ] Stub model test, a failure doesn't stop the run: the claim agent raises on the first claim, and the other two are still decided and the run finishes
- [ ] Stub model test, a retry: a claim fails, goes back in the queue, is worked again later in the same run and is decided, with `failures` 1. The retry doesn't count against the cap
- [ ] Stub model test, two failures: the claim is `left_for_handler` and the stub marks its item `for_handler`
- [ ] Stub model test, the check for missed claims: `finish_run` with a waiting claim under the cap is refused and names the claim; the stub works it, and `finish_run` is then accepted
- [ ] Stub model test: when the queue agent itself raises, the run is finished with a summary that says it stopped, and no claim is left in progress
- [ ] Test: a claim left in progress with no decision by an earlier run is `waiting` with `failures` 1 and an `error` step once the next run starts
- [ ] `curl -s localhost:8000/api/instructions` returns `queue` and `claim`
- [ ] vitest and the browser: `/instructions` shows "Running the queue" and "Working a claim", with no text box, input or edit button
- [ ] `uv run -m agent --help` shows the cap and the claim id
- [ ] `npm run check` passes

## Phase 4: Dashboard: the run and its to-do list

Add the "This run" panel to the queue page and the Left for a handler state across the dashboard.

- [ ] vitest covers the panel with no run, a running run with an item in each state, and a finished run with its summary, and the fifth tile, against a stubbed `fetch`
- [ ] e2e: with the queue open, the test starts a run and writes a to-do list through the API. Without a reload, the list appears; after the test ticks an item off and finishes the run, the page shows Done on that item, Finished and the summary
- [ ] Browser, `/`: before any run, the panel says "No run yet". The tiles show five states, with Left for a handler at 0
- [ ] Browser, with `browser_evaluate`: each to-do chip and the Left for a handler chip have the colors from the design
- [ ] Browser: screenshots of the queue with a run in light and dark mode show rounded panels with no outlines, no one-edge borders and no gradients
- [ ] Browser: `browser_console_messages` shows no errors
- [ ] `npm run check` passes

## Phase 5: Dashboard: what the agent read, and failures

Add the "What the agent read" panel, the `reading` and `error` steps, and the left-for-handler message on the claim page.

- [ ] vitest covers the panel with and without readings, each step kind, and the decision panel for a claim left for a handler
- [ ] e2e: the test starts a claim and records a `reading` step through the API. Without a reload, it appears in "What the agent read"
- [ ] e2e: the test starts and releases a claim twice through the API. Without a reload, the page shows Left for a handler, both errors in the steps and "after 2 tries" in the decision panel
- [ ] Browser: on a claim with both, readings and errors are easy to tell apart from tool calls, and errors use Raspberry
- [ ] Browser: `browser_console_messages` shows no errors
- [ ] `npm run check` passes

## Phase 6: The documents and the live trial

Update `docs/SPEC.md` (decisions follow the manual as well as the wording; the manual leaves "Not for now"; the to-do list and the new state are among what the team sees), `docs/TECH_STACK.md` (the default model, the two agents and the entry points) and `docs/STATUS.md`. Then run the live trial the brief asks for.

- [ ] Live, in the browser: after reseeding, with `npm run dev` running and the queue open, `uv run -m agent --cap 5` runs to the end. Snapshots taken during the run show the to-do list appearing, items moving to In progress and then Done, and the page ends on Finished with the summary
- [ ] Live: afterwards, `curl -s localhost:8000/api/claims` shows exactly five claims worked (decided, waiting for sign-off or left for a handler), 20 `waiting` and none `in_progress`
- [ ] Live: every decision has a section and a reason of two or three sentences; every approval over $1,000 is waiting for sign-off with no payment, and every other approval is paid exactly its payout
- [ ] Live, in the browser: each of the five claim pages shows its steps and at least one section in "What the agent read"
- [ ] `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` describe the product as it now is, and `docs/STATUS.md` records the live run
- [ ] `grep -rn evals backend agent dashboard/src` finds nothing
- [ ] `npm run check` passes

## Not in this plan

- Scoring the agent against the handlers' decisions in `data/evals/`, which we're not to open unless asked.
- A way for handlers to decide a claim left for a handler on the dashboard. The claim shows that it needs a person and why.
- Starting a run from the dashboard, and working claims in parallel.
- Keeping a run's progress if the process is stopped, beyond releasing its stuck claims at the next start.
- Letters to customers, sign-in and real payments, as `docs/SPEC.md` says.
