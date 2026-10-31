"""The UnderCover Agent."""

import json
import os
import uuid
from typing import Any

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from agent.tools import CLAIM_TOOLS, REFUSED, request

load_dotenv(override=True)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
MODEL_TIMEOUT = 120
RETRIES = 3
RETRY_DELAY = 1.0
CLAIM_CALL_LIMIT = 30
DOCUMENT_NAMES = {"policy_wording": "Policy wording", "claims_manual": "Claims manual"}


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
        timeout=MODEL_TIMEOUT,
    )


def middleware(call_limit: int) -> list[AgentMiddleware[Any, Any, Any]]:
    """Retry failed model calls and unreachable tools, and stop an agent that loops."""
    return [
        ModelRetryMiddleware(
            max_retries=RETRIES, on_failure="error", initial_delay=RETRY_DELAY
        ),
        ToolRetryMiddleware(
            max_retries=RETRIES,
            retry_on=(httpx.TransportError,),
            on_failure="error",
            initial_delay=RETRY_DELAY,
        ),
        ModelCallLimitMiddleware(run_limit=call_limit, exit_behavior="error"),
    ]


class BackendError(Exception):
    """The backend refused a request the agent's run depends on."""


def call_backend(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Call the backend and return its JSON, raising if it refuses."""
    response = request(method, path, body)
    if response.is_error:
        raise BackendError(f"{response.status_code}: {response.json()['detail']}")
    return response.json()


def steps(message: AnyMessage) -> list[tuple[str, str]]:
    """Turn one message from the agent's run into steps for the dashboard."""
    if isinstance(message, ToolMessage):
        found = [("tool_result", f"{message.name}: {message.text}")]
        if message.name == "read_section" and not message.text.startswith(REFUSED):
            section = json.loads(message.text)
            document = DOCUMENT_NAMES[section["document"]]
            found.append(
                (
                    "reading",
                    f"{document}, section {section['number']}: {section['title']}",
                )
            )
        return found
    found = []
    if message.text:
        found.append(("message", message.text))
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in call["args"].items())
            found.append(("tool_call", f"{call['name']}({args})"))
    return found


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Work a started claim with a fresh claim agent, recording each step."""
    instructions = call_backend("GET", "/api/instructions")["text"]
    agent = create_agent(
        llm or model(),
        tools=CLAIM_TOOLS,
        system_prompt=instructions,
        middleware=middleware(CLAIM_CALL_LIMIT),
        checkpointer=InMemorySaver(),
    )
    states = agent.stream(
        {"messages": [{"role": "user", "content": f"Claim {claim_id}"}]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="values",
    )
    messages = next(states)["messages"]
    for state in states:
        for message in state["messages"][len(messages) :]:
            for kind, content in steps(message):
                call_backend(
                    "POST",
                    f"/api/claims/{claim_id}/steps",
                    {"kind": kind, "content": content},
                )
        messages = state["messages"]
    return messages[-1].text


def describe(error: Exception) -> str:
    """Say in one short line what went wrong."""
    return f"{type(error).__name__}: {error}".splitlines()[0][:300]


def outcome(claim: dict[str, Any]) -> str:
    """Say how a decided claim ended: the decision, the payout and the payment."""
    decision = claim["decision"]
    line = f"{decision['decision']}  ${decision['payout']:,.2f}"
    if decision["decision"] != "approve":
        return line
    if claim["payment"] is not None:
        return f"{line}  paid"
    if claim["status"] == "waiting_for_sign_off":
        return f"{line}  waiting for sign-off"
    return f"{line}  not paid"


def release(claim_id: str, reason: str) -> str:
    """Put a failed claim back in the queue, or leave it for a handler."""
    claim = call_backend("POST", f"/api/claims/{claim_id}/release", {"reason": reason})
    failures = claim["failures"]
    tries = f"{failures} failed {'try' if failures == 1 else 'tries'}"
    if claim["status"] == "left_for_handler":
        return f"failed: {reason}. Left for a handler after {tries}"
    return f"failed: {reason}. Back in the queue after {tries}"


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Work one waiting claim with a fresh claim agent and report back in a line."""
    response = request("GET", f"/api/claims/{claim_id}")
    if response.is_error:
        return f"{claim_id}  not started: {response.json()['detail']}"
    status = response.json()["status"]
    if status != "waiting":
        return f"{claim_id}  not started: it is {status.replace('_', ' ')}"
    thread_id = str(uuid.uuid4())
    call_backend("POST", f"/api/claims/{claim_id}/start", {"thread_id": thread_id})
    try:
        run(claim_id, thread_id, llm)
    except Exception as error:  # a failed claim goes back in the queue
        failure = describe(error)
    else:
        failure = "The agent finished without recording a decision"
    claim = call_backend("GET", f"/api/claims/{claim_id}")
    if claim["decision"] is not None:
        return f"{claim_id}  {outcome(claim)}"
    return f"{claim_id}  {release(claim_id, failure)}"


def work_queue() -> None:
    """Work every waiting claim in queue order, printing a line for each."""
    worked = 0
    for claim in call_backend("GET", "/api/claims"):
        if claim["status"] == "waiting":
            print(work_claim(claim["claim_id"]), flush=True)
            worked += 1
    print(f"Worked {worked} claims")
