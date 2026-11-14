"""The dispatcher: code with no model that works a dispatch's or an evaluation's claims
with up to N claim agents at once. Each claim is worked by the claim agent on its own
thread, so the dispatcher saves no progress of its own: the next dispatch finishes
what a stopped one left."""

import logging
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph, StateNode
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy, Send

from agent import api, harness

log = logging.getLogger(__name__)

LIST_CLAIMS = "list_claims"
WORK_CLAIM = "work_claim"
FINISH_RUN = "finish_run"
# A rate limit or a timeout that outlasts the model's own retries is waited out twice
# more, each time carrying the claim on as the same attempt.
RETRIES = RetryPolicy(max_attempts=3, initial_interval=5.0, retry_on=harness.PASSING)
TO_WORK = (api.Status.IN_PROGRESS, api.Status.WAITING)


class Dispatch(TypedDict):
    """What the dispatcher keeps for one run: the claims to work."""

    claims: list[str]


class ClaimToWork(TypedDict):
    """What a claim agent is sent: the claim it works."""

    claim_id: str


@dataclass(frozen=True)
class DispatchContext:
    """The run being worked, the claim agent, and the claims the agent's service is
    resuming after a sign-off, which a dispatch leaves to it."""

    run: harness.Run
    agent: harness.ClaimAgent
    resuming: Collection[str]


def list_claims(state: Dispatch, runtime: Runtime[DispatchContext]) -> dict[str, Any]:
    """List the claims to work: an evaluation's copies, which the backend made for
    it, or for a dispatch every claim in progress and every waiting claim, oldest
    submitted first, recorded on the run."""
    context = runtime.context
    if context.run.evaluation:
        copies = api.get_run(context.run.run_id)["claims"]
        return {"claims": [copy["claim_id"] for copy in copies]}
    queue = sorted(api.list_claims(), key=lambda claim: claim["submitted_on"])
    claims = [
        c["claim_id"]
        for c in queue
        if c["status"] in TO_WORK and c["claim_id"] not in context.resuming
    ]
    api.add_run_claims(context.run.run_id, claims)
    return {"claims": claims}


def fan_out(state: Dispatch) -> list[Send] | str:
    """Send each claim to a claim agent, or finish a run with nothing to work."""
    sends = [Send(WORK_CLAIM, ClaimToWork(claim_id=c)) for c in state["claims"]]
    return sends or FINISH_RUN


def work_claim(state: ClaimToWork, runtime: Runtime[DispatchContext]) -> None:
    """Work one claim for the run. A claim that fails and comes back to the queue is
    tried once more, as a new attempt; the backend leaves it for a handler after two."""
    context, claim_id = runtime.context, state["claim_id"]
    if claim_id in context.resuming:  # signed off since it was listed
        return
    if harness.work_on(claim_id, context.run, context.agent) == api.Status.WAITING:
        harness.work_on(claim_id, context.run, context.agent)


def left_in_progress(state: ClaimToWork, error: NodeError) -> Command[str]:
    """Leave a claim whose waits ran out in progress for the next dispatch, or one that
    failed outside the claim agent as it stands, and go on to finish the run, so that
    no error stops the dispatch."""
    reason = harness.describe(error.error)
    if isinstance(error.error, harness.PASSING):
        log.warning("%s  left in progress: %s", state["claim_id"], reason)
    else:
        log.warning("%s  failed outside the claim agent: %s", state["claim_id"], reason)
    return Command(goto=FINISH_RUN)


def finish_run(state: Dispatch, runtime: Runtime[DispatchContext]) -> None:
    """Finish the run, once every claim agent has finished."""
    api.finish_run(runtime.context.run.run_id)


def dispatcher() -> CompiledStateGraph[Dispatch, DispatchContext, Any, Any]:
    """Build the dispatcher's graph, which has no model and no checkpointer."""
    builder = StateGraph(Dispatch, context_schema=DispatchContext)
    builder.add_node(LIST_CLAIMS, list_claims)
    # LangGraph passes a handler its NodeError by the parameter's name, a signature
    # its type hints don't list yet.
    handler = cast("StateNode[ClaimToWork, DispatchContext]", left_in_progress)
    builder.add_node(
        WORK_CLAIM, work_claim, retry_policy=RETRIES, error_handler=handler
    )
    builder.add_node(FINISH_RUN, finish_run)
    builder.add_edge(START, LIST_CLAIMS)
    builder.add_conditional_edges(LIST_CLAIMS, fan_out, [WORK_CLAIM, FINISH_RUN])
    builder.add_edge(WORK_CLAIM, FINISH_RUN)
    builder.add_edge(FINISH_RUN, END)
    return builder.compile()


def dispatch(
    run: harness.Run,
    agent: harness.ClaimAgent,
    agents: int,
    resuming: Collection[str],
) -> None:
    """Work the run's claims with up to agents claim agents at once."""
    context = DispatchContext(run, agent, resuming)
    dispatcher().invoke({"claims": []}, {"max_concurrency": agents}, context=context)
