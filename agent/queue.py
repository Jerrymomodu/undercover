"""The queue agent, which works the queue by handing each claim to a claim agent."""

import threading
import uuid
from collections.abc import Callable
from typing import Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver

from agent.main import call_backend, describe, middleware, model, work_claim
from agent.tools import reply, request

BASE_CALLS = 10
CALLS_PER_CLAIM = 5
RECURSION_LIMIT = 1_000
STUCK = "The previous run stopped before this claim was decided"

ClaimModels = Callable[[str], BaseChatModel | None]


class Todo(TypedDict):
    content: str
    status: Literal["to_do", "in_progress", "done", "for_handler"]


def waiting_claims() -> list[dict]:
    """Return the claims waiting in the queue."""
    return [c for c in call_backend("GET", "/api/claims") if c["status"] == "waiting"]


def release_stuck_claims() -> None:
    """Put back claims an earlier run left in progress with no decision."""
    for claim in call_backend("GET", "/api/claims"):
        if claim["status"] == "in_progress" and claim["decision"] is None:
            call_backend(
                "POST", f"/api/claims/{claim['claim_id']}/release", {"reason": STUCK}
            )


class QueueRun:
    """One run over the queue: its cap, the claims it has started and its summary."""

    def __init__(self, cap: int | None, claim_models: ClaimModels) -> None:
        self.run_id = str(uuid.uuid4())
        self.cap = cap
        self.claim_models = claim_models
        self.started: set[str] = set()
        self.summary: str | None = None
        self.lock = threading.Lock()

    def at_cap(self) -> bool:
        """Say whether the run has started as many claims as its cap allows."""
        return self.cap is not None and len(self.started) >= self.cap

    def work(self, claim_id: str) -> str:
        """Work one claim with a claim agent, unless the cap is reached."""
        with self.lock:
            if self.at_cap() and claim_id not in self.started:
                return (
                    f"{claim_id}  not started: this run's cap of {self.cap} claims"
                    " is reached"
                )
            response = request("GET", f"/api/claims/{claim_id}")
            if response.is_success and response.json()["status"] == "waiting":
                self.started.add(claim_id)
            line = work_claim(claim_id, self.claim_models(claim_id))
            print(line, flush=True)
            return line

    def finish(self, summary: str) -> str:
        """Finish the run, unless a waiting claim within the cap has been missed."""
        missed = [c["claim_id"] for c in waiting_claims()]
        if missed and not self.at_cap():
            return (
                f"Not finished: {len(missed)} claims are still waiting within the"
                f" run's cap: {', '.join(missed)}. Work them, then finish."
            )
        self.record(summary)
        return "The run is finished."

    def record(self, summary: str) -> str:
        """Record the run's summary with the backend."""
        call_backend("POST", f"/api/runs/{self.run_id}/finish", {"summary": summary})
        self.summary = summary
        return summary


def queue_tools(run: QueueRun) -> list[BaseTool]:
    """Build the queue agent's tools for one run."""

    @tool
    def list_claims() -> str:
        """List the claims waiting in the queue, with their type, amount and date."""
        lines = [
            f"{c['claim_id']}  {c['claim_type']}  ${c['amount_claimed']:,.2f}"
            f"  submitted {c['submitted_on']}"
            for c in waiting_claims()
        ]
        return "\n".join(lines) or "No claims are waiting."

    @tool
    def write_todos(todos: list[Todo]) -> str:
        """Replace the whole to-do list, giving each item its current status."""
        response = request("PUT", f"/api/runs/{run.run_id}/todos", {"todos": todos})
        return "The to-do list is saved." if response.is_success else reply(response)

    @tool
    def work_claim(claim_id: str) -> str:
        """Hand one waiting claim to a fresh claim agent and get back how it ended."""
        return run.work(claim_id)

    @tool
    def finish_run(summary: str) -> str:
        """Finish the run with a summary for the handlers, once no claim is missed."""
        return run.finish(summary)

    return [list_claims, write_todos, work_claim, finish_run]


def work_queue(
    cap: int | None,
    llm: BaseChatModel | None = None,
    claim_models: ClaimModels = lambda _: None,
) -> str:
    """Work the queue, or up to cap claims, with the queue agent; return the summary."""
    release_stuck_claims()
    run = QueueRun(cap, claim_models)
    call_backend("POST", "/api/runs", {"run_id": run.run_id, "cap": cap})
    claims = cap or len(waiting_claims())
    agent = create_agent(
        llm or model(),
        tools=queue_tools(run),
        system_prompt=call_backend("GET", "/api/instructions")["queue"],
        middleware=middleware(BASE_CALLS + CALLS_PER_CLAIM * claims),
        checkpointer=InMemorySaver(),
    )
    task = f"Work up to {cap} claims." if cap else "Work the whole queue."
    try:
        agent.invoke(
            {"messages": [{"role": "user", "content": task}]},
            config={
                "configurable": {"thread_id": run.run_id},
                "recursion_limit": RECURSION_LIMIT,
            },
        )
    except Exception as error:  # the run is finished either way
        ending = f"The run stopped: {describe(error)}"
    else:
        ending = "The run ended before the agent finished it."
    summary = run.summary or run.record(ending)
    print(summary)
    return summary
