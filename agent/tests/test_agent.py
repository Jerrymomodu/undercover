import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import __main__ as cli
from agent import main

CLAIM = "CLM-1001"
BLOCKED = "A payout over $1,000.00 needs a handler's sign-off."


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    def bind_tools(self, tools, **kwargs):
        return self


class BrokenModel(StubModel):
    """A chat model that fails, as a model provider sometimes does."""

    def _generate(self, *args, **kwargs):
        raise RuntimeError("The model is unavailable.")


def calls(*tool_calls):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": str(i)}
            for i, (name, args) in enumerate(tool_calls)
        ],
    )


READ = calls(
    ("get_claim", {"claim_id": CLAIM}),
    ("get_policy", {"policy_id": "POL-2001"}),
    ("get_claim_history", {"customer_id": "CUS-3001"}),
    ("get_policy_wording", {}),
)


def decide(decision, payout):
    return calls(
        (
            "decide_claim",
            {
                "claim_id": CLAIM,
                "decision": decision,
                "payout": payout,
                "reason": "The reason for the decision.",
                "policy_section": "3. Trip Delay",
            },
        )
    )


def stub(*replies):
    return StubModel(messages=iter(replies))


def test_run_declines_a_claim_and_records_each_step(client):
    reply = main.run(
        CLAIM,
        "thread-1",
        stub(READ, decide("decline", 0), AIMessage(content="I declined the claim.")),
    )
    assert reply == "I declined the claim."
    claim = client.get(f"/api/claims/{CLAIM}").json()
    assert claim["status"] == "decided"
    assert claim["decision"]["reason"] == "The reason for the decision."
    assert claim["decision"]["policy_section"] == "3. Trip Delay"

    steps = client.get(f"/api/claims/{CLAIM}/steps").json()
    assert {s["thread_id"] for s in steps} == {"thread-1"}
    tool_calls = [s["text"].split()[0] for s in steps if s["kind"] == "tool_call"]
    assert tool_calls == [
        "get_claim",
        "get_policy",
        "get_claim_history",
        "get_policy_wording",
        "decide_claim",
    ]
    assert steps[-1] == steps[-1] | {"kind": "reply", "text": "I declined the claim."}
    results = {
        s["text"].split(":")[0]: s["text"] for s in steps if s["kind"] == "tool_result"
    }
    assert set(results) == set(tool_calls)
    assert results["get_claim"].startswith('get_claim: {"claim_id":"CLM-1001"')
    assert results["get_policy_wording"].endswith("...")
    assert len(results["get_policy_wording"]) == len("get_policy_wording: ") + 503


def test_run_approves_and_pays_within_the_limit(client):
    main.run(
        CLAIM,
        "thread-1",
        stub(
            READ,
            decide("approve", 420),
            calls(("pay_claim", {"claim_id": CLAIM, "amount": 420})),
            AIMessage(content="I approved and paid $420.00."),
        ),
    )
    claim = client.get(f"/api/claims/{CLAIM}").json()
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 420.0


def test_the_agent_cannot_pay_over_the_limit(client):
    main.run(
        CLAIM,
        "thread-1",
        stub(
            READ,
            decide("approve", 1250),
            calls(("pay_claim", {"claim_id": CLAIM, "amount": 1250})),
            AIMessage(content="I approved $1,250.00; the payment waits for sign-off."),
        ),
    )
    claim = client.get(f"/api/claims/{CLAIM}").json()
    assert claim["status"] == "awaiting_sign_off"
    assert claim["payment"] is None
    steps = client.get(f"/api/claims/{CLAIM}/steps").json()
    paid = [s["text"] for s in steps if s["text"].startswith("pay_claim:")]
    assert paid == [f'pay_claim: Refused (403): {{"detail":"{BLOCKED}"}}']


def test_a_run_without_a_decision_puts_the_claim_back(client):
    main.run(CLAIM, "thread-1", stub(READ, AIMessage(content="I am not sure.")))
    assert client.get(f"/api/claims/{CLAIM}").json()["status"] == "waiting"
    steps = client.get(f"/api/claims/{CLAIM}/steps").json()
    assert steps[-1]["kind"] == "note"
    assert steps[-1]["text"] == main.NO_DECISION


def test_a_failed_run_puts_the_claim_back(client):
    with pytest.raises(RuntimeError, match="unavailable"):
        main.run(CLAIM, "thread-1", BrokenModel(messages=iter([])))
    assert client.get(f"/api/claims/{CLAIM}").json()["status"] == "waiting"


def test_a_claim_in_progress_cannot_be_run_again(client):
    client.post(f"/api/claims/{CLAIM}/start", json={"thread_id": "thread-1"})
    with pytest.raises(Exception, match="409"):
        main.run(CLAIM, "thread-2", stub(AIMessage(content="Hello")))


def test_the_agent_reads_its_instructions_from_the_api(client, monkeypatch):
    prompts = []
    create_agent = main.create_agent

    def spy(llm, tools, system_prompt):
        prompts.append(system_prompt)
        return create_agent(llm, tools=tools, system_prompt=system_prompt)

    monkeypatch.setattr(main, "create_agent", spy)
    main.run(CLAIM, "thread-1", stub(AIMessage(content="Hello")))
    assert prompts == [client.get("/api/instructions").json()["content"]]
    assert "pay_claim" in prompts[0]


def test_cli_runs_the_claims_given(client, monkeypatch):
    runs = []
    monkeypatch.setattr(main, "run", lambda c, t: runs.append(c) or "Done.")
    cli.work(["CLM-1002", "CLM-1003"])
    assert runs == ["CLM-1002", "CLM-1003"]


def test_cli_works_every_waiting_claim(client, monkeypatch):
    client.post(f"/api/claims/{CLAIM}/start", json={"thread_id": "thread-1"})
    runs = []
    monkeypatch.setattr(main, "run", lambda c, t: runs.append(c) or "Done.")
    cli.work([])
    assert len(runs) == 24
    assert CLAIM not in runs


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert main.model().model_name == "openai/gpt-6-luna"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"
