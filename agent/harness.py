"""The harness: builds the claim agent, and works one claim on its own thread."""

import contextvars
import json
import logging
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from time import perf_counter
from typing import Any, cast

from langchain.tools import ToolException
from langchain_core.exceptions import ModelRateLimitError, ModelTimeoutError
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.ai import UsageMetadata
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import ChatOpenAI
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from psycopg import Connection, sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool
from pydantic import SecretStr

from agent import api
from agent.tools import CLAIM_TOOLS, ClaimContext, ClaimState

log = logging.getLogger(__name__)

ClaimGraph = CompiledStateGraph[ClaimState, ClaimContext, Any, Any]
Pool = ConnectionPool[Connection[DictRow]]
Messages = dict[str, list[BaseMessage]]
Start = Messages | Command | None

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-6-luna"
DEFAULT_EFFORT = "low"
NO_EFFORT = "none"
SCHEMA = "undercover"
CONNECTIONS = 4
# Claim agents wait for one of the process's connections rather than fail.
CONNECTION_WAIT_SECONDS = 600
CLAIM_MODEL_CALLS = 30
NO_DECISION = "The agent finished without recording a decision"
WORK_CLAIM = "Work claim"
CARRY_ON = "Carry on"
AGENT = "agent"
TOOLS = "tools"
PAUSE = "wait_for_sign_off"
PAY = "pay"
# The errors a dispatch waits out and carries the claim on from, as the same attempt.
PASSING = (ModelRateLimitError, ModelTimeoutError)


class TooManyModelCalls(Exception):
    """The claim agent made as many model calls as it may without finishing."""


@dataclass(frozen=True)
class ClaimAgent:
    """The claim agent: its model, and a new saver for each claim run, because a
    saver holds a lock around every read and write."""

    llm: BaseChatModel
    saver: Callable[[], BaseCheckpointSaver[Any]]

    def graph(self) -> ClaimGraph:
        """Build a claim graph on a saver of its own."""
        return claim_graph(self.llm, self.saver())


@dataclass(frozen=True)
class Run:
    """A dispatch or an evaluation that claim agents work claims in."""

    run_id: str
    evaluation: bool


def chosen_model() -> tuple[str, str | None]:
    """Return the model named in MODEL_NAME, with no reasoning effort set, or GPT-6
    Luna with low reasoning effort by default."""
    if name := os.getenv("MODEL_NAME"):
        return name, None
    return DEFAULT_MODEL, DEFAULT_EFFORT


def model() -> ChatOpenAI:
    """Return the chosen model on OpenRouter."""
    name, effort = chosen_model()
    return ChatOpenAI(
        model=name,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=effort,
        timeout=120,
        max_retries=5,
    )


@contextmanager
def connections() -> Iterator[Pool]:
    """Open the process's connections to Postgres at DATABASE_URL, at most
    CONNECTIONS of them, where the claim graph saves its progress in our own schema."""
    settings = {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
        "options": f"-c search_path={SCHEMA}",
    }
    with Pool(
        os.environ["DATABASE_URL"],
        min_size=1,
        max_size=CONNECTIONS,
        kwargs=settings,
        timeout=CONNECTION_WAIT_SECONDS,
    ) as pool:
        with pool.connection() as connection:
            create = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")
            connection.execute(create.format(sql.Identifier(SCHEMA)))
        PostgresSaver(pool).setup()
        yield pool


def claim_agent(llm: BaseChatModel, pool: Pool) -> ClaimAgent:
    """The claim agent on the model, saving each claim run's progress on the pool."""
    return ClaimAgent(llm, partial(PostgresSaver, pool))


def refusal(error: Exception) -> str:
    """Show the model why a tool was refused, and let any other error stop the agent."""
    if isinstance(error, api.Refused):
        return f"Refused with status {error}"
    if isinstance(error, ToolException):
        return f"Refused: {error}"
    raise error


def record_reply(claim_id: str, reply: BaseMessage) -> None:
    """Record the model's reply on the claim: its text, then each tool it calls."""
    if reply.text:
        api.record_step(claim_id, "message", reply.text)
    if isinstance(reply, AIMessage):
        for call in reply.tool_calls:
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in call["args"].items())
            api.record_step(claim_id, "tool_call", f"{call['name']}({args})")


def record_result(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Run a tool and record its result on the claim, then any step it gives as its
    artifact, such as a section it read."""
    result = execute(request)
    if isinstance(result, ToolMessage):
        message = result
    else:
        message = cast(dict[str, Any], result.update)["messages"][0]
    claim_id = cast(ClaimContext, request.runtime.context).claim_id
    api.record_step(claim_id, "tool_result", f"{message.name}: {message.text}")
    if message.artifact:
        api.record_step(claim_id, *message.artifact)
    return result


def record_usage(context: ClaimContext, reply: AIMessage) -> None:
    """Record the tokens and cost of a model reply, as OpenRouter reports them, with
    the claim and its run."""
    usage = cast(UsageMetadata, reply.usage_metadata)
    metadata = reply.response_metadata
    call: api.ModelCall = {
        "run_id": context.run_id,
        "model": metadata["model_name"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cost": metadata["token_usage"]["cost"],
    }
    api.record_model_call(context.claim_id, call)


def call_model(
    state: ClaimState,
    runtime: Runtime[ClaimContext],
    llm: Runnable[LanguageModelInput, BaseMessage],
    instructions: SystemMessage,
) -> dict[str, Any]:
    """Ask the model for its next step, up to CLAIM_MODEL_CALLS times in all, and
    record its reply and what it cost on the claim."""
    calls = state["model_calls"]
    if calls >= CLAIM_MODEL_CALLS:
        message = f"The claim agent made {calls} model calls without finishing"
        raise TooManyModelCalls(message)
    reply = cast(AIMessage, llm.invoke([instructions, *state["messages"]]))
    record_usage(runtime.context, reply)
    record_reply(runtime.context.claim_id, reply)
    return {"messages": [reply], "model_calls": 1}


def wait_for_sign_off(state: ClaimState, runtime: Runtime[ClaimContext]) -> None:
    """Pause until a handler signs off the payout, which the backend records. On
    resume this runs again from the top, so nothing comes before the interrupt."""
    interrupt({"claim_id": runtime.context.claim_id})


def pay(state: ClaimState, runtime: Runtime[ClaimContext]) -> dict[str, Any]:
    """Pay the approved payout, which the backend refuses unless it may be paid."""
    claim = api.pay_claim(runtime.context.claim_id, state["decision"]["payout"])
    return {"status": claim["status"]}


def after_agent(state: ClaimState) -> str:
    """Run the tools the model asked for, or stop: it finished without a decision."""
    reply = state["messages"][-1]
    return TOOLS if isinstance(reply, AIMessage) and reply.tool_calls else END


def after_tools(state: ClaimState) -> str:
    """Go back to the model until a decision is recorded, then pay an approval, after
    a sign-off if the backend holds it, or stop."""
    decision, status = state["decision"], state["status"]
    if not decision:
        return AGENT
    if status == api.Status.WAITING_FOR_SIGN_OFF:
        return PAUSE
    if decision["decision"] == api.APPROVE and status == api.Status.IN_PROGRESS:
        return PAY
    return END


def claim_graph(llm: BaseChatModel, saver: BaseCheckpointSaver[Any]) -> ClaimGraph:
    """Build the claim agent's graph, which saves its progress after every step."""
    instructions = SystemMessage(api.get_instructions()["claim"])
    builder = StateGraph(ClaimState, context_schema=ClaimContext)
    builder.add_node(
        AGENT,
        partial(call_model, llm=llm.bind_tools(CLAIM_TOOLS), instructions=instructions),
    )
    builder.add_node(
        TOOLS,
        ToolNode(CLAIM_TOOLS, handle_tool_errors=refusal, wrap_tool_call=record_result),
    )
    builder.add_node(PAUSE, wait_for_sign_off)
    builder.add_node(PAY, pay)
    builder.add_edge(START, AGENT)
    builder.add_conditional_edges(AGENT, after_agent, [TOOLS, END])
    builder.add_conditional_edges(TOOLS, after_tools, [AGENT, PAUSE, PAY, END])
    builder.add_edge(PAUSE, PAY)
    builder.add_edge(PAY, END)
    return builder.compile(checkpointer=saver)


def thread_of(claim: dict[str, Any]) -> RunnableConfig:
    """Address the claim's thread, where the claim graph saves its progress."""
    return {"configurable": {"thread_id": claim["thread_id"]}}


def claim_config(
    claim: dict[str, Any], name: str, run_id: str | None
) -> RunnableConfig:
    """Run on the claim's thread, traced in Langfuse in the session of that thread
    and tagged with its run, so a whole run can be found together."""
    session = f"{claim['claim_id']}:{claim['thread_id']}"
    metadata: dict[str, Any] = {
        "langfuse_session_id": session,
        "langfuse_trace_name": name,
    }
    if run_id:
        metadata["langfuse_tags"] = [run_id]
    return thread_of(claim) | {
        "callbacks": [CallbackHandler()],
        "metadata": metadata,
        # One tool call at a time, so two decisions in one reply can't race.
        "max_concurrency": 1,
    }


def ask(text: str) -> Messages:
    """Give an agent one message from the user."""
    return {"messages": [HumanMessage(text)]}


def begin(claim_id: str) -> Messages:
    """Give a claim agent its first message, naming the claim it works on."""
    return ask(f"Claim {claim_id}")


def describe(error: BaseException) -> str:
    """Say in one line what went wrong."""
    lines = str(error).splitlines()
    return f"{type(error).__name__}: {lines[0]}" if lines else type(error).__name__


def report(claim: dict[str, Any], reason: str) -> str:
    """Say in one line how a claim ended: its decision and payout, or why it failed."""
    claim_id, status, decision = claim["claim_id"], claim["status"], claim["decision"]
    if status == api.Status.WAITING:
        return f"{claim_id}  failed: {reason}, back in the queue"
    if status == api.Status.LEFT_FOR_HANDLER:
        return f"{claim_id}  failed: {reason}, left for a handler"
    line = f"{claim_id}  {decision['decision']}  ${decision['payout']:,.2f}"
    if status == api.Status.WAITING_FOR_SIGN_OFF:
        return f"{line}, waiting for sign-off"
    if decision["decision"] == api.APPROVE and claim["payment"] is None:
        return f"{line}, not paid yet"
    return line


def run_claim_graph(
    graph: ClaimGraph,
    start: Start,
    claim: dict[str, Any],
    name: str,
    run_id: str | None,
) -> str | None:
    """Run the claim graph on the claim's thread, saving each step, and say what went
    wrong, if anything. A rate limit or a timeout goes through to the dispatcher, with
    the claim left in progress, so it can wait and carry the claim on."""
    try:
        # A fresh context makes this a root run even inside the dispatcher's worker,
        # so it is never a subgraph, and Langfuse puts it in the claim's session.
        contextvars.Context().run(
            graph.invoke,
            start,
            claim_config(claim, name, run_id),
            context=ClaimContext(claim["claim_id"], run_id),
            durability="sync",
        )
    except PASSING:
        raise
    except Exception as error:  # a claim that fails must not stop the dispatch
        return describe(error)
    return None


@contextmanager
def timed(claim_id: str, run_id: str | None) -> Iterator[None]:
    """Record how long the agent works on a claim in one go, with its run."""
    clock = perf_counter()
    try:
        yield
    finally:
        api.record_work_time(claim_id, run_id, perf_counter() - clock)


def settle(claim_id: str, error: str | None) -> str:
    """Fail a claim the agent left undecided, and report how the claim ended. An
    error after the decision is logged, and the claim keeps its decision."""
    claim = api.get_claim(claim_id)
    reason = error or NO_DECISION
    if claim["status"] == api.Status.IN_PROGRESS and claim["decision"] is None:
        claim = api.fail_claim(claim_id, reason)
    elif error:
        log.warning("%s  %s", claim_id, error)
    line = report(claim, reason)
    log.info(line)
    return line


def work_claim(claim_id: str, graph: ClaimGraph, run_id: str | None) -> str:
    """Work one claim from a clean start, as a new attempt, and report how it ended."""
    claim = api.start_claim(claim_id, str(uuid.uuid4()))
    with timed(claim_id, run_id):
        error = run_claim_graph(graph, begin(claim_id), claim, WORK_CLAIM, run_id)
    return settle(claim_id, error)


def carry_on(claim_id: str, graph: ClaimGraph, run_id: str | None) -> str:
    """Carry a claim in progress on from its saved progress, as the same attempt, and
    report how it ended. A claim at the pause has been signed off, so it resumes past
    it. One with nothing saved, stopped before its first step, starts on its own
    thread; any other carries on, finishing a step whose writes were saved."""
    claim = api.get_claim(claim_id)
    saved = graph.get_state(thread_of(claim))
    start: Start = None
    if saved.next == (PAUSE,):
        start = Command(resume=True)
    elif saved.created_at is None and claim["decision"] is None:
        start = begin(claim_id)
    with timed(claim_id, run_id):
        error = run_claim_graph(graph, start, claim, CARRY_ON, run_id)
    return settle(claim_id, error)


def work_on(claim_id: str, run: Run, agent: ClaimAgent) -> str:
    """Carry a claim in progress on, or start a waiting one, for a dispatch or an
    evaluation, on a claim graph of its own. Return where the claim stands after; one
    that has moved on since it was listed is left as it is. Nobody signs off an
    evaluation's copy, so a held approval counts as finished and its progress goes."""
    status = api.get_claim(claim_id)["status"]
    if status == api.Status.IN_PROGRESS:
        carry_on(claim_id, agent.graph(), run.run_id)
    elif status == api.Status.WAITING:
        work_claim(claim_id, agent.graph(), run.run_id)
    else:
        return status
    claim = api.get_claim(claim_id)
    if run.evaluation and claim["status"] == api.Status.WAITING_FOR_SIGN_OFF:
        agent.saver().delete_thread(claim["thread_id"])
    return claim["status"]
