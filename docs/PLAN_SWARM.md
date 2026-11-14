# Plan: a swarm of claim agents and a scoreboard

This plan builds what `docs/SWARM.md` asks for on top of the durable build, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

SIDENOTE: For consistency with the course, please read `labs/week2day4.ipynb` and build the dispatcher in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

When it's done, a handler starts a dispatch from the queue page and chooses how many claim agents work at once. A dispatcher with no model works every claim in progress and every waiting claim, oldest submitted first, with up to N claim agents at once. Each claim is still worked by the claim graph on its own thread, with its progress saved, its pause for a sign-off and its recovery after a restart. A rate limit or a timeout carries the claim on as the same attempt. Any other failure puts the claim back in the queue, and the same dispatch tries it once more. Every model call's tokens and cost, and the agent's time on each claim, are recorded with their dispatch or evaluation. A new Scoreboard page runs evaluations on copies of the labelled claims and scores them against the handlers' decisions. The agent runs on GPT-6 Luna by default.

## Design

### Modules

The backend:

- `database.py`: the tables, the engine and seeding, as today. The tables change: the runs table now holds dispatches and evaluations, and new tables hold each run's claims, the model calls, the agent's work times, the held-out claims and the answer key. The to-do table goes. Seeding also reads the three files in `data/evals/` (the brief allows this), into the answer key and held-out tables only.
- `scoring.py` (new): one job. It works out an evaluation's measures from the backend's records and the answer key. It holds the costs of mistakes ($1,500 and $50) and the dollar of leeway on a payout, and it uses `models.py` and nothing else. No claim operation imports it.
- `agent_service.py`: the backend's only way to reach the agent's service. It gains `start_dispatch(agents)` and `start_evaluation(agents, eval_set, tiny)`, beside `resume_claim`.
- `main.py`: the operations. It gains the run, cost and evaluation operations below and uses `scoring`.
- `models.py`, `documents.py`, `payout.py` and `seed.py` keep their jobs.

The agent, now in five parts:

- `api.py`: the backend's API. It loses the to-do and queue-run functions and gains `record_model_call`, `record_work_time`, `create_dispatch`, `create_evaluation`, `add_run_claims`, `get_run`, `finish_run` and `stop_runs`. It gets no function for the answer key or the scores.
- `tools.py`: the claim agent's tools and the context and state they read. `ClaimContext` gains `run_id` (a run's id, or `None`). The queue tools and `RunContext` go.
- `harness.py`: builds and runs the claim agent. It loses the queue agent and its middleware. It gains `work_on(claim_id, run, agent)`, the one function the dispatcher calls, and a `ClaimAgent` that builds a claim graph on a saver of its own for each claim run.
- `dispatcher.py` (new): the dispatcher, a LangGraph graph with no model, and `dispatch(run, agent, agents)` to run it. It uses `harness` and `api`.
- `service.py`: the agent's service. It gains `start_dispatch` and `start_evaluation`, refuses a second start with a 409, and marks any run still running as stopped when it starts. It uses `dispatcher`, `harness` and `api`.
- `__main__.py` keeps only `uv run -m agent CLM-1001`, and `console.py` is unchanged.

The dependencies run one way: `service` uses `dispatcher` and `harness`; `dispatcher` uses `harness` and `api`; `harness` uses `tools` and `api`; `tools` uses `api`. The backend and the agent still never import each other.

The dashboard gains a Scoreboard page (`/scoreboard`) and an evaluation's page (`/scoreboard/:runId`). The run panel on the queue page becomes the dispatch panel. The end-to-end stand-in for the agent's service also answers the two starts.

### The dispatcher

`agent/dispatcher.py`, in the lab's style:

```
START → list_claims ──Send per claim──▶ work_claim → finish_run → END
```

- **State:** `Dispatch`, a `TypedDict` with `claims: list[str]`, as in the lab. What a run needs to know comes through `context_schema=DispatchContext` (the run's id and kind, the claim agent, and the claims the service is resuming), LangChain's way of telling a node what it needs to know.
- **`list_claims`:** for a dispatch, the claims in progress and the waiting claims, oldest submitted first, leaving out any claim the service is resuming after a sign-off. It records them on the run with `add_run_claims`, which the run panel shows. For an evaluation, it lists the copies the backend made for the run, read with `get_run`. Copies never appear in `list_claims`, so a dispatch never carries one on.
- **`fan_out`:** a conditional edge that returns one `Send("work_claim", claim_id)` for each claim, as in the lab.
- **`work_claim`:** calls `harness.work_on(claim_id, run, agent)`. If the claim comes back to the queue, this is the first failure in this dispatch (a second would leave it for a handler), so it calls `work_on` once more, as a new attempt. Its `RetryPolicy` has `retry_on=(ModelRateLimitError, ModelTimeoutError)` from `langchain_core.exceptions`, which `ChatOpenAI` raises once its own 5 retries run out. Its `error_handler` takes the `NodeError`, logs it and returns, so a claim whose retries have run out stays in progress for the next dispatch, and no error ever stops the dispatch.
- **`finish_run`:** runs once, after every claim agent has finished, because LangGraph waits for every task in a step before it starts the next one. (This is the lab assignment's `score_run` pattern.) It calls `finish_run` on the backend, which scores nothing: the backend works out every measure from its records when they are read.
- **`dispatch(run, agent, agents)`** invokes the graph with `{"max_concurrency": agents}`, as the lab does.
- **No checkpointer on the dispatcher.** Each claim saves its own progress on its own thread, and the next dispatch finishes what a stopped one left. The claim graph is invoked in a fresh `contextvars.Context`, as today, so it is never a subgraph of the dispatcher and keeps its own thread, checkpointer and Langfuse trace.

### Following the lab

As in the lab: the `Dispatch` state with a list of claims; `list_claims` and `fan_out` with `Send`; a `work_claim` worker; `RetryPolicy` on the worker; `max_concurrency` in the config, set to N; and a node after the workers that runs once when they have all finished.

Where the brief differs, we follow the brief:

- The worker calls the claim agent through `harness.work_on`, in place of the lab's stand-in or its in-notebook agent.
- `retry_on` is limited to rate limits and timeouts, and an `error_handler` keeps every other error from stopping the dispatch. The lab retried every error.
- No results are collected in the dispatcher's state, and nothing is scored in the graph. The backend records each claim's decision, cost and time, and works out the scoreboard from those records. The lab gathered results with `operator.add` and scored them in the notebook.
- Each claim keeps its own thread, so a claim that waits days for a sign-off holds up nothing. The lab ran the whole swarm on one thread, and its information box explains why the product doesn't.
- Cost comes from `usage.cost` on each model reply, as in the lab, but each call is recorded on the backend as it happens, rather than summed at the end.

### Working one claim: `harness.work_on`

`work_on(claim_id, run, agent)` reads the claim. If it is in progress, it carries it on (`carry_on`) as the same attempt; if it is waiting, it starts it as a new attempt (`work_claim`). It returns the claim's status after settling, from the backend's record, and logs the report line as today.

- **Rate limits and timeouts:** `run_claim_graph` lets `ModelRateLimitError` and `ModelTimeoutError` through without settling the claim. The claim stays in progress with its progress saved, the dispatcher's `RetryPolicy` runs `work_claim` again, and `work_on` finds the claim in progress and carries it on from its last saved step. The backend never decides or pays a claim twice, so this is safe.
- **Any other error** is caught and settled as today: an undecided claim goes back to the queue, or is left for a handler after its second attempt.
- **Evaluations:** for a copy that the backend holds for sign-off, `work_on` deletes the thread's saved progress (`delete_thread` on the claim graph's saver). The copy counts as finished, and nobody can sign it off.
- **Langfuse:** each claim keeps its own session, as today, and its trace carries `langfuse_tags: [run_id]` in the metadata when it runs in a dispatch or an evaluation.

### Savers and connections

- `harness.connections()` replaces `checkpointer()`. It opens the process's one `ConnectionPool` of at most 4 connections, with the settings and schema as today, runs `setup()` once and yields the pool. The pool's `timeout` is raised so that claim agents wait for a connection rather than fail.
- `ClaimAgent(llm, saver)` holds the model and a function that gives a new saver. `ClaimAgent.graph()` builds a claim graph on a fresh `PostgresSaver(pool)` for each claim run. `PostgresSaver` holds a lock around every read and write, so one saver shared by 25 claim agents would make them take turns. The tests give every graph the same `InMemorySaver`.
- The backend keeps its pool of 4 and gains a longer `pool_timeout`, so a burst of requests from 25 claim agents waits for a connection rather than fails.
- In all: the backend 4, the agent's service 4 and Supabase's `pg_net` 1, so at most 9, within the 12 the brief allows. A `uv run -m agent CLM-1001` running at the same time adds 4.

### Runs: dispatches and evaluations

The `runs` table now holds both kinds:

| Column | Meaning |
| --- | --- |
| `number` | Counts up, as today; it orders runs and names copies |
| `run_id` | A UUID |
| `kind` | `dispatch` or `evaluation` |
| `agents` | N, from 1 to 25 |
| `status` | `running`, `finished` or `stopped` |
| `started_at`, `finished_at` | Times |
| `eval_set`, `tiny` | For an evaluation: `evaluation` or `held_out`, and whether it is the five `tiny` claims; empty for a dispatch |
| `model`, `reasoning_effort` | The model's name and its effort, or `none` when `MODEL_NAME` chose the model |

`run_claims` links a run to the claims it works: a dispatch's claims, in the order it listed them, or an evaluation's copies.

### Cost and time

- `model_calls`: one row per model reply, with the claim, the run (or none), the model, the input and output tokens from `usage_metadata`, and the cost from `response_metadata["token_usage"]["cost"]`, as OpenRouter reports them. The claim graph's `agent` node records each one with `record_model_call`, straight after the reply, whatever happens next.
- `work_times`: one row per claim graph run, with the claim, the run (or none), when it started and how many seconds it took. `run_claim_graph` times each invoke, whether it ends in a decision, a pause or an error. A wait for a sign-off falls between two invokes, so it is never counted.
- A run's totals are the sums of its own rows, failed attempts included. A `carry_on` after a sign-off happens outside any run, so it is recorded with no run.

### Evaluations

- **Seeding** stores the 25 held-out claims in `held_out_claims`, outside the queue, and the handlers' decisions for both sets in `answer_key` (set, claim id, decision, payout, `tiny`). No claim operation reads either table, and only `scoring.py` reads the answer key.
- **`create_evaluation`** copies the set's claims (the queue's 25 original records for `evaluation`, or the held-out ones), whole or just the five `tiny` ones. Each copy gets a new id, `E<run number>-<claim id>` such as `E3-CLM-1101`, written into its record too. A copy has `evaluation_id` set to its run and `copy_of` set to the original's id, and starts out waiting.
- **Copies stay out of the queue.** `list_claims` leaves them out, so the queue page's counts and a dispatch never see them. `get_claim` serves a copy like any claim, with nothing from the answer key, so its page and its steps work.
- **No sign-off on a copy.** `sign_off_claim` refuses a copy with a 409, and a copy's page has no sign-off form. An approval the backend holds counts as finished, and its saved progress is cleared, as above.
- **A stopped evaluation** shows as stopped, and its unfinished copies count as undecided.

### The scoreboard's measures

`scoring.py` follows the lab's `is_right` and `mistake_cost`. A copy the agent didn't decide counts as a referral with a payout of 0:

- `decision_accuracy`: the share of claims where the agent's decision matches the handler's.
- `accuracy`: the decision matches, and the payout is within a dollar.
- `cost_of_mistakes`:
  - A right decision costs nothing, except a right approval with the wrong amount, which costs the difference.
  - A wrong decline costs $1,500.
  - A wrong approval costs its payout, whether it was paid or not.
  - A needless referral costs $50.
- `straight_through`: the share of claims not referred.
- `cost_per_claim`: the run's model cost divided by its claims.
- `seconds_per_claim`: the average of the agent's time on each claim.
- `run_seconds`: from the run's start to its finish.

### API

The backend, new and changed. Every operation keeps an `operation_id`, a one-line docstring and no optional inputs. A field that a dispatch leaves empty is still required, and is sent as `null`.

| Operation | Route | What it does |
| --- | --- | --- |
| `start_dispatch` | `POST /api/dispatch/start` | Body `{agents}`. Asks the agent's service to start a dispatch. Passes on its 202 or 409, and returns 503 "The agent's service isn't running" when it can't be reached |
| `start_evaluation` | `POST /api/evaluations/start` | Body `{agents, eval_set, tiny}`. The same, for an evaluation |
| `create_dispatch` | `POST /api/dispatches` | Body `{agents, model, reasoning_effort}`. The service records a new dispatch |
| `create_evaluation` | `POST /api/evaluations` | Body `{agents, eval_set, tiny, model, reasoning_effort}`. Records an evaluation and makes its copies |
| `add_run_claims` | `PUT /api/runs/{run_id}/claims` | Body `{claim_ids}`. The claims a dispatch works |
| `get_run` | `GET /api/runs/{run_id}` | A run with its claims and its summary |
| `finish_run` | `POST /api/runs/{run_id}/finish` | No body. Marks a running run finished |
| `stop_runs` | `POST /api/runs/stop` | No body. Marks every running run stopped |
| `get_latest_dispatch` | `GET /api/dispatches/latest` | The newest dispatch with its claims, summary, cost and time, or `null` |
| `list_evaluations` | `GET /api/evaluations` | The evaluations, newest first, with their measures |
| `get_evaluation` | `GET /api/evaluations/{run_id}` | One evaluation's measures and claims, with the handler's decision and payout beside the agent's |
| `record_model_call` | `POST /api/claims/{claim_id}/model-calls` | Body `{run_id, model, input_tokens, output_tokens, cost}` |
| `record_work_time` | `POST /api/claims/{claim_id}/work-times` | Body `{run_id, started_at, seconds}` |
| `sign_off_claim` | as today | Also refuses an evaluation's copy with a 409 |
| `get_instructions` | as today | Returns only the claim agent's instructions |

`start_run`, `get_latest_run` and `write_todos` go. `agents` must be from 1 to 25 (422 otherwise), and `eval_set` must be `evaluation` or `held_out`.

The summary on a run is built from the records, never by a model: how many of its claims were approved, declined and referred; each payout waiting for a sign-off, with its claim and amount; and each claim left for a handler or still in progress.

The agent's service gains:

| Operation | Route | What it does |
| --- | --- | --- |
| `start_dispatch` | `POST /api/dispatches` | Body `{agents}`. Returns 202 straight away, or 409 while a run is going. Then, in a background task, it creates the dispatch through the backend and runs the dispatcher |
| `start_evaluation` | `POST /api/evaluations` | Body `{agents, eval_set, tiny}`. The same, for an evaluation |

The service allows one run at a time, with a lock it holds from the start until the run finishes. It keeps a set of the claims `resume_claim` is carrying on, which a dispatch skips. When it starts, it calls `stop_runs`. The claim agent gets no tool for starting a run.

### What goes

The queue agent, its middleware, `backend/instructions/queue.md`, `write_todos`, the `todos` table and its end-to-end test, and `uv run -m agent` without a claim id. Seeding drops the old `todos` table by name before `drop_all`, because on Supabase it still references `runs`. `uv run -m agent CLM-1001` still works one claim, with no run.

### The default model

`DEFAULT_MODEL` becomes `openai/gpt-6-luna` with low reasoning effort. `MODEL_NAME` still chooses another model, which runs with no reasoning effort set, and a run records that as `none`.

### Dashboard

- **The dispatch panel**, on the queue page in place of the run panel:
  - A number from 1 to 25, starting at 3, and a "Start dispatch" button. A refusal shows the backend's message, such as "A dispatch or evaluation is already running" or "The agent's service isn't running".
  - The latest dispatch, refreshed every two seconds: its status, N, its claims with where each stands (linked to their pages), and its model cost and time.
  - When it finishes or stops, the summary: approved, declined and referred, each payout waiting for a sign-off, and each claim left for a handler or still in progress.
- **The Scoreboard page** (`/scoreboard`):
  - A form to start an evaluation: the set (the evaluation set or the held-out set), the whole set or just the five `tiny` claims, and N.
  - The evaluations, newest first. Each row shows when it started, the set, N, the model and its effort, the status (Running, Finished or Stopped) and every measure. Each row opens the evaluation's page.
- **An evaluation's page** (`/scoreboard/:runId`): its measures, then a row per claim, with the handler's decision and payout beside the agent's and the agent's reason. A miss is marked in Raspberry. Each claim links to its copy's page.
- **A copy's page** has no sign-off form, and says it is an evaluation's copy of the original claim.
- **The header** links to the queue, the scoreboard and the instructions. The instructions page shows the claim agent's instructions alone.
- Styled to `BRAND.md` in light and dark mode. The decisions keep their colors, and money looks like $1,250.00.

### End-to-end tests

- The stand-in for the agent's service also answers `POST /api/dispatches` and `POST /api/evaluations` with 202, and lists the bodies it was sent at `GET /api/started`.
- Starting a dispatch with N=5, and an evaluation of the held-out set's tiny claims with N=4, on the dashboard both reach the stand-in with those values.
- The dispatch panel test replaces the to-do test. It plays a dispatch through the API (create it, add its claims, decide them, finish it) and watches the panel show its claims, then its summary.
- The scoreboard test plays an evaluation through the API, as `e2e/run.spec.ts` does with a run today. It creates it, decides its copies (one of them wrongly), records their model calls and work times, and finishes it. Then it checks the scoreboard's row and the evaluation's page, with the miss marked.

### Checked against the code standards

- **One way to call each service:** the agent reaches the backend through `api.py`, the dashboard through `api.ts`, and the backend reaches the agent's service through `agent_service.py`. Each URL and path is written once.
- **Five parts, kept apart:** the dispatcher only chooses the claims and keeps track of the run, and it touches the claim agent only through `harness.work_on`. The service only receives calls and hands them on. Scoring is its own module in the backend, and no claim operation imports it.
- **The framework's own way:** `StateGraph`, `Send`, `RetryPolicy` with `retry_on`, a node `error_handler` with `NodeError`, `max_concurrency`, `context_schema`, `PostgresSaver` and `delete_thread`, LangChain's `ModelRateLimitError` and `ModelTimeoutError`, `usage_metadata`, FastAPI's `BackgroundTasks`, and SQLAlchemy Core.
- **Functions do one job:**
  - `work_on` chooses between carrying on and starting.
  - `run_claim_graph` invokes the graph and times it.
  - `settle` settles the claim.
  - The worker works a claim for the dispatch.
  - `finish_run` closes the run.
- **No defensive code beyond what the brief asks:** one catch per claim in the harness, the worker's `error_handler`, and the backend's catch when the service can't be reached.
- **Instructions stay goals.** Only the queue instructions go.
- **Rules 10 and 13** are updated for the dispatcher, the fifth part.

### How the criteria are checked

- **Tests:** pytest and vitest, with a stub model, `InMemorySaver`, SQLite and stand-ins for Langfuse and the agent's service. None of them calls a model or needs the network.
- **API calls:** curl against `npm run dev`.
- **Pages:** checked in the browser with the Playwright MCP server, at `http://localhost:5173`.
- **Supabase:** checked through its read-only MCP server.
- **Langfuse:** checked through its API, with a short `uv run python -c`.
- **Live runs:** the brief asks for one reseed and only the runs it lists, so phases 1 to 5 use no real model. Pages that need a dispatch or an evaluation are filled through the API, as the end-to-end tests do. The live runs all come in phase 6, after one `npm run seed`, with the default model.

## Phase 1: GPT-6 Luna, and the cost and time of every claim

Change the default model. Add the `model_calls` and `work_times` tables, `record_model_call` and `record_work_time`. `ClaimContext` gains `run_id`, which is `None` until phase 2, when runs become dispatches. The `agent` node records each reply's tokens and cost, and `run_claim_graph` records the time of each invoke.

- [x] pytest: with no `MODEL_NAME`, `model()` is `openai/gpt-6-luna` with reasoning effort `low`. With `MODEL_NAME=openrouter/free` it is that model with no reasoning effort
- [x] pytest, backend: `record_model_call` and `record_work_time` store their rows for a claim, with a run or with `null`. An unknown claim returns 404, and negative tokens, cost or seconds return 422
- [x] Stub model test: the stub's replies carry `usage_metadata` and a `token_usage.cost`. Working `CLM-1001` records one model call per reply, with its tokens and cost, and one work time
- [x] Stub model test, over the limit: `CLM-1002` pauses for sign-off, then waits (the test's clock moves on by an hour) before the sign-off and the carry-on. It has two work times, and their total leaves out the hour
- [x] Stub model test: a claim that fails with an error still has its model calls and work time recorded
- [x] The shared OpenAPI test passes with the new operations
- [x] `npm run check` passes

## Phase 2: The dispatcher in place of the queue agent

Reshape `runs`, add `run_claims`, and add `create_dispatch`, `add_run_claims`, `get_run`, `finish_run` and `stop_runs`. Build `agent/dispatcher.py`, `harness.work_on`, `ClaimAgent` with a saver for each claim run, and `connections()`. Add the service's `start_dispatch`, with its lock, its skip set and `stop_runs` at startup. Tag each claim's trace with its run. Remove the queue agent, its middleware, `queue.md`, the to-do list and `uv run -m agent` without a claim id. Drop the old `todos` table when seeding.

- [x] pytest: the dispatcher's graph has the nodes `list_claims`, `work_claim` and `finish_run`, a conditional edge from `list_claims` to `work_claim`, and no checkpointer. `work_claim` has a `RetryPolicy` on `ModelRateLimitError` and `ModelTimeoutError` and an `error_handler`
- [x] pytest, with `harness.work_on` replaced by one that sleeps and counts the claims at work: with 12 waiting claims and N=3, never more than 3 are worked at once, every claim is worked once, and `finish_run` runs once, after the last
- [x] pytest: a dispatch lists the claims in progress and the waiting claims, oldest submitted first, records them on the run, and skips a claim in the service's resuming set, a decided claim and a claim left for a handler
- [x] Stub model test: the stub raises a `ModelRateLimitError` after the claim agent has read the claim. The dispatch carries the claim on as the same attempt, on the same thread. The second prompt holds the earlier tool result, and the claim has one decision and attempts 1
- [x] Stub model test: with the retries run out, the claim stays in progress with its progress saved, no `error` step and attempts 1. The dispatch works the other claims and finishes. The next dispatch carries the claim on as the same attempt
- [x] Stub model test: a claim that fails with any other error goes back to the queue and is tried once more in the same dispatch, as attempt 2 on a new thread. A claim that fails both times is left for a handler, and the dispatch still finishes
- [x] Stub model test: a claim in progress, stopped partway, is carried on by the next dispatch, and a claim signed off while the service was away is paid by it
- [x] Stub model test: each claim run's graph has a saver of its own (`ClaimAgent.graph()` gives a new saver each time)
- [x] Stub model test: each claim's root run keeps its session and carries `langfuse_tags` with the run's id. `uv run -m agent CLM-1001` (stubbed) runs with no tag and records its cost with no run
- [x] Service test: `start_dispatch` with N=3 returns 202, creates a dispatch with N, the model and its effort, and runs the dispatcher. A second start while it runs returns 409. N=0 or N=26 returns 422
- [x] Service test: on startup the service marks a running run as stopped
- [x] `uv run -m agent` with no claim id prints its usage and exits with an error. `uv run -m agent CLM-1001` (stubbed) works one claim
- [x] `grep -rn "write_todos\|queue_agent\|run_queue\|todos" agent backend dashboard/src e2e` finds only the retired table's name, which seeding drops, and `backend/instructions/queue.md` is gone
- [x] `curl -s localhost:8000/api/instructions` returns only the claim instructions
- [x] `npm run seed` on Supabase succeeds with the old `todos` table in place, and Supabase MCP then shows no `todos` table in `undercover`, and `runs` with its new columns
- [x] The shared OpenAPI test passes for the backend and the agent's service
- [x] `npm run check` passes

## Phase 3: Starting a dispatch from the dashboard

Add `start_dispatch` to the backend and `agent_service.py`, `get_latest_dispatch` with the summary, cost and time, and the dispatch panel. Update the stand-in and the end-to-end tests.

- [ ] pytest, backend: `start_dispatch` sends N to the agent's service (a recorder in its place) and returns 202. A 409 from the service returns 409 with its message. A service that can't be reached returns 503 "The agent's service isn't running"
- [ ] pytest, backend: the summary of a finished dispatch, built from records: 2 approved (one paid, one waiting for sign-off at $1,350.00), 1 declined, 1 referred, 1 left for a handler and 1 still in progress, with the claim ids and the amount
- [ ] pytest, backend: the dispatch's cost and time are the sums of its own model calls and work times, failed attempts included, and leave out rows with no run or another run
- [ ] `grep -rn "UNDERCOVER_AGENT\|8002" backend --include=*.py` finds them only in `backend/agent_service.py`
- [ ] vitest: the dispatch panel's number starts at 3 and accepts 1 to 25, the start sends N, a refusal shows its message, a running dispatch shows its claims, and a finished one shows its summary, cost and time
- [ ] e2e: on the queue page, setting N to 5 and pressing "Start dispatch" reaches the stand-in with `{"agents": 5}`
- [ ] e2e: a dispatch played through the API shows its claims as each one moves, then its summary when it finishes, without a reload
- [ ] Browser, with `npm run dev` running and the agent's service stopped: "Start dispatch" says the agent's service isn't running
- [ ] Browser: screenshots of the dispatch panel, running and finished (filled through the API), in light and dark mode, show rounded panels with no outlines, no one-edge borders and no gradients. `browser_console_messages` shows no errors
- [ ] `npm run check` passes

## Phase 4: Evaluations

Seed `held_out_claims` and `answer_key`. Add `create_evaluation` with its copies, `scoring.py`, `list_evaluations`, `get_evaluation`, `start_evaluation` in the backend, `agent_service.py` and the service, and the dispatcher's listing for an evaluation. Clear a held copy's progress. Refuse a sign-off on a copy, and leave the form off a copy's page.

- [ ] `npm run seed` and `uv run -m backend.seed` still print 25 claims. Supabase MCP shows 25 rows in `held_out_claims` and 50 in `answer_key`, and `list_claims` still returns the 25 queue claims
- [ ] pytest, backend: `create_evaluation` of the held-out set's tiny claims makes 5 waiting copies with ids like `E1-CLM-11..`, whose records carry the new ids. `list_claims` and the queue's counts are the same before and after
- [ ] pytest, backend: `get_claim` on a copy has no field from the answer key, and its JSON doesn't contain the handler's reason for the original
- [ ] pytest, backend: `sign_off_claim` on a copy waiting for sign-off returns 409 and changes nothing
- [ ] pytest, `scoring.py`: on six claims worked out by hand, one of each kind of outcome (right, right approval with the wrong amount, wrong decline, wrong approval, needless referral and undecided), every measure matches the figure worked out by hand
- [ ] Stub model test: an evaluation of three copies, one approved over the limit, leaves the queue as it was. The held copy counts as finished, its thread has nothing saved, and the evaluation's measures come from the backend
- [ ] Stub model test: a dispatch running after an evaluation never lists its copies
- [ ] Service test: `start_evaluation` returns 202 and creates the evaluation with its set, `tiny`, N, the model and its effort. A start while a dispatch runs returns 409
- [ ] `grep -rn "answer_key\|evals" agent dashboard/src` finds nothing, and in the backend only `database.py` reads `data/evals/` and only `scoring.py` reads `answer_key`
- [ ] vitest: a copy's page has no sign-off form and says it is an evaluation's copy
- [ ] `npm run check` passes

## Phase 5: The scoreboard

Add the Scoreboard page, an evaluation's page, the header link and the end-to-end tests.

- [ ] vitest: the start form sends the set, `tiny` and N; the list shows each evaluation with its status and every measure, newest first; an evaluation's page marks a miss and links each copy to its page
- [ ] e2e: starting an evaluation of the held-out set's tiny claims with N=4 on the Scoreboard page reaches the stand-in with those values
- [ ] e2e: an evaluation played through the API, with one copy decided wrongly, appears on the scoreboard with its measures. Its page shows the handler's decision beside the agent's, the miss marked, and a link to the copy's page
- [ ] Browser: the scoreboard and an evaluation's page (filled through the API), in light and dark mode, follow `BRAND.md`, with no errors in `browser_console_messages`
- [ ] `npm run check` passes

## Phase 6: The live runs, and the documents

After one `npm run seed`, with `npm run dev` running and the default model, run the brief's live checks through the Playwright MCP server. Then bring the documents up to date.

- [ ] Live: start a dispatch at N=3. Partway through, kill every process listening on port 8002: uvicorn's reloader and its worker. On this Windows machine, that's `Get-NetTCPConnection -LocalPort 8002 -State Listen` for the process ids, then `taskkill /F /T` on each. `npm run dev` then stops the others; start it again. The service marks the dispatch stopped
- [ ] Live: a dispatch at N=25 carries on the claims left in progress as the same attempts (same thread ids and attempts) and works the rest with 25 at once, which the claims' first work times show. Its run takes well under the sum of its claims' times
- [ ] Live: comparing claims worked from the start, each takes about as long at N=25 as the claims did at N=3. If they are slower, the report says where the time goes, keeping to 4 connections
- [ ] Live: claims held for sign-off wait. A sign-off on the dashboard pays within five seconds (`browser_wait_for`). No claim fails for want of a database connection
- [ ] Live: during the dispatch, Supabase MCP shows no more than 12 connections whose user is `postgres` in `pg_stat_activity`, checked several times
- [ ] Live: through Langfuse's API, the claims of the N=25 dispatch are found together by its run id tag
- [ ] Live: an evaluation of the evaluation set at N=25, and one of the held-out set's five tiny claims at N=5, appear on the scoreboard with every measure, and the queue page's counts are the same before and after
- [ ] `docs/SPEC.md`: its sections on working the queue and on what the team needs to see describe the dispatch, the problems put right, the scoreboard and the cost and time. Its Rules are unchanged
- [ ] `docs/TECH_STACK.md`: GPT-6 Luna by default, the dispatcher as the fifth part, `work_on`, the savers on the shared pool, the service's starts, cost from `usage.cost`, and Langfuse tags
- [ ] `docs/PROCESS.md`: these runs replace the five-claim cap
- [ ] `docs/CODE_STANDARDS.md`: rule 10 names `Send`, `RetryPolicy` and `error_handler` for the dispatcher, in place of middleware for the queue agent. Rule 13 gives the agent five parts
- [ ] `docs/STATUS.md` describes what's built, how to start a dispatch and an evaluation, and the results of the live runs
- [ ] `npm run check` passes, both with `.env` in place and with it moved out of the way

## Not in this plan

- Pointing the dispatcher at the agent in the cloud. `work_on` is the one place to change.
- Resuming a stopped evaluation. It stays stopped, and a new one can be started.
- Clearing old checkpoints and old copies, beyond a held copy's progress. `npm run seed` rebuilds the backend's tables.
- Rejecting a held payout, sign-in, real payments and messages to customers, as `SPEC.md` says.
