"""The UnderCover Agent."""

import json
import os
from collections.abc import Iterator
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

load_dotenv(override=True)

BACKEND_URL = "http://localhost:8000"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-6-luna"
STEP_LENGTH = 500
NO_DECISION = "The run ended without a decision, so the claim is back in the queue."


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=30)


def send(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Call the backend for the agent's run, raising on any refusal."""
    with backend() as client:
        response = client.request(method, path, json=body)
    response.raise_for_status()
    return response.json()


def call(method: str, path: str, body: dict[str, Any] | None = None) -> str:
    """Call the backend for a tool, passing a refusal back to the model."""
    with backend() as client:
        response = client.request(method, path, json=body)
    if response.is_success:
        return response.text
    return f"Refused ({response.status_code}): {response.text}"


@tool
def get_claim(claim_id: str) -> str:
    """Get a claim: the customer's story, the items claimed and the documents."""
    return call("GET", f"/api/claims/{claim_id}")


@tool
def get_policy(policy_id: str) -> str:
    """Get a policy: the plan's limits, the add-ons, the trip and the travelers."""
    return call("GET", f"/api/policies/{policy_id}")


@tool
def get_claim_history(customer_id: str) -> str:
    """Get the customer's earlier claims."""
    return call("GET", f"/api/customers/{customer_id}/claim-history")


@tool
def get_policy_wording() -> str:
    """Get the policy wording, which every decision follows."""
    return call("GET", "/api/policy-wording")


@tool
def decide_claim(
    claim_id: str,
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    reason: str,
    policy_section: str,
) -> str:
    """Record the decision on a claim, with the payout (0 unless approved), the
    reason in two or three sentences and the policy section it rests on."""
    return call(
        "POST",
        f"/api/claims/{claim_id}/decision",
        {
            "decision": decision,
            "payout": payout,
            "reason": reason,
            "policy_section": policy_section,
        },
    )


@tool
def pay_claim(claim_id: str, amount: float) -> str:
    """Pay an approved claim its approved payout."""
    return call("POST", f"/api/claims/{claim_id}/payment", {"amount": amount})


TOOLS = [
    get_claim,
    get_policy,
    get_claim_history,
    get_policy_wording,
    decide_claim,
    pay_claim,
]


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or GPT-6 Luna by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
    )


def shorten(text: str) -> str:
    return text if len(text) <= STEP_LENGTH else text[:STEP_LENGTH] + "..."


def steps(message: BaseMessage) -> list[tuple[str, str]]:
    """Turn one message from the agent into the steps the dashboard shows."""
    if isinstance(message, AIMessage):
        calls = [
            ("tool_call", f"{c['name']} {json.dumps(c['args'])}")
            for c in message.tool_calls
        ]
        return calls + ([("reply", message.text)] if message.text else [])
    if isinstance(message, ToolMessage):
        return [("tool_result", f"{message.name}: {shorten(message.text)}")]
    return []


def record(claim_id: str, thread_id: str, kind: str, text: str) -> None:
    send(
        "POST",
        f"/api/claims/{claim_id}/steps",
        {"thread_id": thread_id, "kind": kind, "text": text},
    )


def stream_steps(
    llm: BaseChatModel, instructions: str, claim_id: str, thread_id: str
) -> Iterator[tuple[str, str]]:
    """Run the agent on the claim, yielding its steps as it takes them."""
    agent = create_agent(llm, tools=TOOLS, system_prompt=instructions)
    for update in agent.stream(
        {"messages": [{"role": "user", "content": f"Decide claim {claim_id}."}]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="updates",
    ):
        for node in update.values():
            for message in node["messages"]:
                yield from steps(message)


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the agent on one claim, recording each step, and return its reply."""
    instructions = send("GET", "/api/instructions")["content"]
    send("POST", f"/api/claims/{claim_id}/start", {"thread_id": thread_id})
    reply = ""
    try:
        for kind, text in stream_steps(
            llm or model(), instructions, claim_id, thread_id
        ):
            record(claim_id, thread_id, kind, text)
            if kind == "reply":
                reply = text
    finally:
        if send("GET", f"/api/claims/{claim_id}")["status"] == "in_progress":
            record(claim_id, thread_id, "note", NO_DECISION)
            send("POST", f"/api/claims/{claim_id}/release")
    return reply
