import itertools

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from agent import __main__ as cli
from agent import main
from agent.tools import CLAIM_TOOLS


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies and keeps the prompts it was sent."""

    prompts: list[list[BaseMessage]] = []

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(messages)
        return super()._generate(messages, stop, run_manager, **kwargs)


class BrokenModel(StubModel):
    """A chat model whose provider fails on its first `failures` calls."""

    failures: int = 1_000

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("The model provider is unavailable")
        return super()._generate(messages, stop, run_manager, **kwargs)


def call(name, text="", **args):
    return AIMessage(
        content=text, tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}]
    )


def replies(claim_id, policy_id, customer_id, decision, payout, *extra):
    return [
        call("get_claim", claim_id=claim_id),
        call("get_policy", policy_id=policy_id),
        call("get_claim_history", customer_id=customer_id),
        call(
            "record_decision",
            claim_id=claim_id,
            decision=decision,
            payout=payout,
            section="Section 3, Trip Delay",
            reason="The delay was covered.",
        ),
        *extra,
        AIMessage(content=f"Decision: {decision}."),
    ]


def script(*args):
    return StubModel(messages=iter(replies(*args)))


def start(client, claim_id, thread_id):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": thread_id})


def test_tools_are_named_after_backend_operations(client):
    operations = {
        operation["operationId"]
        for path in client.get("/openapi.json").json()["paths"].values()
        for operation in path.values()
    }
    names = [t.name for t in CLAIM_TOOLS]
    assert names == [
        "get_claim",
        "get_policy",
        "get_claim_history",
        "list_sections",
        "read_section",
        "record_decision",
        "pay_claim",
    ]
    assert set(names) <= operations


def test_get_instructions(client):
    text = client.get("/api/instructions").json()["text"]
    assert text.startswith("# UnderCover Agent: working a claim")
    assert "read_section" in text
    assert "## 10. How we work out your payment" not in text


def test_run_approves_and_pays_within_the_limit(client):
    start(client, "CLM-1001", "thread-1")
    stub = script(
        "CLM-1001",
        "POL-2001",
        "CUS-3001",
        "approve",
        420.0,
        call("pay_claim", text="Paying now.", claim_id="CLM-1001", amount=420.0),
    )
    assert main.run("CLM-1001", "thread-1", stub) == "Decision: approve."

    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["thread_id"] == "thread-1"
    assert claim["decision"]["payout"] == 420.0
    assert claim["payment"]["amount"] == 420.0

    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [s["kind"] for s in steps] == [
        *(["tool_call", "tool_result"] * 4),
        "message",
        "tool_call",
        "tool_result",
        "message",
    ]
    assert steps[0]["content"] == 'get_claim(claim_id="CLM-1001")'
    assert steps[1]["content"].startswith('get_claim: {"claim_id":"CLM-1001"')
    assert steps[8]["content"] == "Paying now."
    assert steps[9]["content"] == 'pay_claim(claim_id="CLM-1001", amount=420.0)'
    assert steps[-1]["content"] == "Decision: approve."
    assert {s["thread_id"] for s in steps} == {"thread-1"}


def test_run_records_the_sections_it_reads(client):
    start(client, "CLM-1001", "thread-1")
    stub = StubModel(
        messages=iter(
            [
                call("list_sections", document="policy_wording"),
                call("read_section", document="policy_wording", number=1),
                call("read_section", document="policy_wording", number=3),
                call("read_section", document="claims_manual", number=10),
                call(
                    "record_decision",
                    claim_id="CLM-1001",
                    decision="approve",
                    payout=420.0,
                    section="Section 3, Trip Delay",
                    reason="Covered.",
                ),
                call("pay_claim", claim_id="CLM-1001", amount=420.0),
                AIMessage(content="Approved."),
            ]
        )
    )
    main.run("CLM-1001", "thread-1", stub)

    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [s["content"] for s in steps if s["kind"] == "reading"] == [
        "Policy wording, section 1: Your plan",
        "Policy wording, section 3: Trip Delay",
        "Claims manual, section 10: Meals without receipts",
    ]
    assert steps[0]["content"] == 'list_sections(document="policy_wording")'
    assert client.get("/api/claims/CLM-1001").json()["payment"]["amount"] == 420.0


def test_an_unknown_section_is_refused_and_not_recorded(client):
    start(client, "CLM-1003", "thread-1")
    stub = StubModel(
        messages=iter(
            [
                call("read_section", document="claims_manual", number=99),
                AIMessage(content="Stopped."),
            ]
        )
    )
    assert main.run("CLM-1003", "thread-1", stub) == "Stopped."
    refusal = stub.prompts[-1][-1]
    assert isinstance(refusal, ToolMessage)
    assert refusal.text.startswith("Refused with status 404")
    steps = client.get("/api/claims/CLM-1003/steps").json()
    assert "reading" not in {s["kind"] for s in steps}


def test_run_uses_the_instructions_from_the_backend(client):
    start(client, "CLM-1003", "thread-1")
    stub = script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)
    main.run("CLM-1003", "thread-1", stub)
    system = stub.prompts[0][0]
    assert isinstance(system, SystemMessage)
    assert system.content == client.get("/api/instructions").json()["text"]


def test_payment_over_the_limit_is_refused(client):
    start(client, "CLM-1002", "thread-2")
    stub = script(
        "CLM-1002",
        "POL-2002",
        "CUS-3002",
        "approve",
        1350.0,
        call("pay_claim", claim_id="CLM-1002", amount=1350.0),
    )
    main.run("CLM-1002", "thread-2", stub)

    refusal = stub.prompts[-1][-1]
    assert isinstance(refusal, ToolMessage)
    assert "needs a handler's sign-off" in refusal.text
    assert refusal.text.startswith("Refused with status 403")

    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "waiting_for_sign_off"
    assert claim["payment"] is None


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_work_claim_declines_and_refers(client, decision):
    stub = script("CLM-1003", "POL-2003", "CUS-3003", decision, 0)
    assert main.work_claim("CLM-1003", stub) == f"CLM-1003  {decision}  $0.00"
    claim = client.get("/api/claims/CLM-1003").json()
    assert claim["status"] == "decided"
    assert claim["decision"]["decision"] == decision
    assert claim["payment"] is None


def test_work_claim_reports_payment(client):
    paid = script(
        "CLM-1001",
        "POL-2001",
        "CUS-3001",
        "approve",
        420.0,
        call("pay_claim", claim_id="CLM-1001", amount=420.0),
    )
    assert main.work_claim("CLM-1001", paid) == "CLM-1001  approve  $420.00  paid"
    held = script(
        "CLM-1002",
        "POL-2002",
        "CUS-3002",
        "approve",
        1350.0,
        call("pay_claim", claim_id="CLM-1002", amount=1350.0),
    )
    assert main.work_claim("CLM-1002", held) == (
        "CLM-1002  approve  $1,350.00  waiting for sign-off"
    )
    unpaid = script("CLM-1003", "POL-2003", "CUS-3003", "approve", 300.0)
    assert main.work_claim("CLM-1003", unpaid) == (
        "CLM-1003  approve  $300.00  not paid"
    )
    assert len(client.get("/api/claims/CLM-1001").json()["thread_id"]) == 36


def test_a_failed_claim_goes_back_in_the_queue(client):
    line = main.work_claim("CLM-1001", BrokenModel(messages=iter([])))
    assert line == (
        "CLM-1001  failed: RuntimeError: The model provider is unavailable."
        " Back in the queue after 1 failed try"
    )
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "waiting"
    assert claim["failures"] == 1
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert steps[-1]["kind"] == "error"
    assert "The model provider is unavailable" in steps[-1]["content"]


def test_a_claim_that_fails_twice_is_left_for_a_handler(client):
    main.work_claim("CLM-1001", BrokenModel(messages=iter([])))
    line = main.work_claim("CLM-1001", BrokenModel(messages=iter([])))
    assert line.endswith("Left for a handler after 2 failed tries")
    assert client.get("/api/claims/CLM-1001").json()["status"] == "left_for_handler"
    assert main.work_claim("CLM-1001", StubModel(messages=iter([]))) == (
        "CLM-1001  not started: it is left for handler"
    )


def test_a_claim_agent_that_ends_without_deciding_is_released(client):
    stub = StubModel(
        messages=iter([call("get_claim", claim_id="CLM-1001"), AIMessage("Done.")])
    )
    assert main.work_claim("CLM-1001", stub) == (
        "CLM-1001  failed: The agent finished without recording a decision."
        " Back in the queue after 1 failed try"
    )
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"


def test_work_claim_needs_a_waiting_claim(client):
    main.work_claim("CLM-1003", script("CLM-1003", "POL-2003", "CUS-3003", "refer", 0))
    assert main.work_claim("CLM-1003", StubModel(messages=iter([]))) == (
        "CLM-1003  not started: it is decided"
    )
    assert main.work_claim("CLM-9999", StubModel(messages=iter([]))) == (
        "CLM-9999  not started: Claim CLM-9999 not found"
    )


def test_a_failed_model_call_is_retried(client):
    stub = BrokenModel(
        failures=1,
        messages=iter(replies("CLM-1003", "POL-2003", "CUS-3003", "refer", 0)),
    )
    assert main.work_claim("CLM-1003", stub) == "CLM-1003  refer  $0.00"
    assert client.get("/api/claims/CLM-1003").json()["failures"] == 0


def test_a_claim_agent_that_loops_is_stopped(monkeypatch, client):
    monkeypatch.setattr(main, "CLAIM_CALL_LIMIT", 3)
    stub = StubModel(
        messages=(call("get_claim", claim_id="CLM-1001") for _ in itertools.count())
    )
    line = main.work_claim("CLM-1001", stub)
    assert "Back in the queue after 1 failed try" in line
    assert len(stub.prompts) == 3
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"


def test_command_line(monkeypatch, capsys):
    monkeypatch.setattr(cli, "work_claim", lambda claim_id: f"{claim_id}  refer")
    cli.main(["CLM-1001"])
    assert capsys.readouterr().out == "CLM-1001  refer\n"


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    default = main.model()
    assert default.model_name == "deepseek/deepseek-v4.1-flash"
    assert default.reasoning_effort == "low"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    chosen = main.model()
    assert chosen.model_name == "openrouter/free"
    assert chosen.reasoning_effort is None
