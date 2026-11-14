"""The dispatcher: code with no model that works the claims with up to N claim agents
at once, each on its own thread."""

import logging
import threading
import time

import pytest
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import RetryPolicy

from agent import api, dispatcher, harness
from agent.tests.interruptions import stop_while_working
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, model_calls_of, steps_of
from agent.tests.stubs import agent_on, call, decide, graph_on, record, stub

QUEUE_ORDER = ["CLM-1001", "CLM-1002", "CLM-1003", "CLM-1004", "CLM-1005"]


@pytest.fixture(autouse=True)
def quick_retries(monkeypatch):
    """Wait out a rate limit in a moment, not seconds."""
    retries = RetryPolicy(
        max_attempts=3, initial_interval=0.01, retry_on=harness.PASSING
    )
    monkeypatch.setattr(dispatcher, "RETRIES", retries)


def dispatch(agent, agents=1, resuming=()):
    """Create a dispatch on the backend and work it, as the agent's service does."""
    run_id = api.create_dispatch(agents, "stub", "none")["run_id"]
    dispatcher.dispatch(harness.Run(run_id, evaluation=False), agent, agents, resuming)
    return api.get_run(run_id)


def rate_limit():
    return ModelRateLimitError("429 Too Many Requests")


def test_the_graph():
    graph = dispatcher.dispatcher()
    drawn = graph.get_graph()
    assert {"list_claims", "work_claim", "finish_run"} <= set(drawn.nodes)
    edges = {(e.source, e.target, e.conditional) for e in drawn.edges}
    assert ("list_claims", "work_claim", True) in edges
    assert ("work_claim", "finish_run", False) in edges
    assert graph.checkpointer is None
    policy = graph.builder.nodes["work_claim"].retry_policy
    assert isinstance(policy, RetryPolicy)
    assert policy.retry_on == harness.PASSING
    assert graph.nodes["work_claim"].error_handler_node


def test_never_more_than_n_claims_at_once(client, monkeypatch):
    waiting = [f"CLM-10{n:02d}" for n in range(1, 13)]
    leave_waiting(*waiting)
    at_work, most, worked, lock = [0], [0], [], threading.Lock()

    def work_on(claim_id, run, agent):
        with lock:
            at_work[0] += 1
            most[0] = max(most[0], at_work[0])
        time.sleep(0.05)
        with lock:
            at_work[0] -= 1
            worked.append(claim_id)
        return api.Status.DECIDED

    monkeypatch.setattr(harness, "work_on", work_on)
    finished = []
    finish_run = api.finish_run
    monkeypatch.setattr(
        api, "finish_run", lambda r: finished.append(len(worked)) or finish_run(r)
    )
    run = dispatch(agent_on(stub()), agents=3)

    assert most[0] == 3
    assert sorted(worked) == waiting
    assert finished == [12]
    assert run["status"] == "finished"


def test_a_dispatch_lists_the_claims_to_work_oldest_first(client, monkeypatch):
    leave_waiting(*QUEUE_ORDER)
    client.post("/api/claims/CLM-1004/start", json={"thread_id": "stopped"})
    client.post("/api/claims/CLM-1005/start", json={"thread_id": "resuming"})
    client.post("/api/claims/CLM-1003/start", json={"thread_id": "t"})
    client.post(
        "/api/claims/CLM-1003/decision",
        json={"decision": "refer", "payout": 0, "section": "S", "reason": "R"},
    )
    worked = []
    monkeypatch.setattr(
        harness, "work_on", lambda c, r, a: worked.append(c) or api.Status.DECIDED
    )
    run = dispatch(agent_on(stub()), resuming={"CLM-1005"})

    by_age = sorted(api.list_claims(), key=lambda c: c["submitted_on"])
    expected = [
        c["claim_id"]
        for c in by_age
        if c["claim_id"] in {"CLM-1001", "CLM-1002", "CLM-1004"}
    ]
    assert worked == expected
    assert [c["claim_id"] for c in run["claims"]] == expected


def test_a_rate_limit_carries_the_claim_on_as_the_same_attempt(client):
    leave_waiting("CLM-1003")
    model = stub(call("get_claim"), rate_limit(), record("refer", 0))
    dispatch(agent_on(model))

    claim = claim_of(client, "CLM-1003")
    assert (claim["status"], claim["attempts"]) == ("decided", 1)
    assert claim["decision"]["decision"] == "refer"
    assert any(isinstance(m, ToolMessage) for m in model.prompts[-1])
    assert {s["thread_id"] for s in steps_of(client, "CLM-1003")} == {
        claim["thread_id"]
    }
    assert "error" not in [s["kind"] for s in steps_of(client, "CLM-1003")]


def test_when_the_waits_run_out_the_claim_stays_in_progress(client, caplog):
    caplog.set_level(logging.WARNING, logger="agent")
    leave_waiting("CLM-1001", "CLM-1003")
    saver = InMemorySaver()
    limited = stub(
        call("get_claim"), rate_limit(), rate_limit(), rate_limit(), *decide("refer", 0)
    )
    run = dispatch(agent_on(limited, saver))

    stuck = claim_of(client, "CLM-1001")
    assert (stuck["status"], stuck["attempts"]) == ("in_progress", 1)
    assert "error" not in [s["kind"] for s in steps_of(client, "CLM-1001")]
    assert claim_of(client, "CLM-1003")["status"] == "decided"
    assert run["status"] == "finished"
    assert any("CLM-1001  left in progress" in m for m in caplog.messages)

    dispatch(agent_on(stub(record("refer", 0)), saver))
    carried = claim_of(client, "CLM-1001")
    assert (carried["status"], carried["attempts"]) == ("decided", 1)
    assert carried["thread_id"] == stuck["thread_id"]


def test_a_failed_claim_is_tried_once_more_in_the_same_dispatch(client):
    leave_waiting("CLM-1003")
    model = stub(RuntimeError("The provider is down"), *decide("refer", 0))
    dispatch(agent_on(model))

    claim = claim_of(client, "CLM-1003")
    assert (claim["status"], claim["attempts"]) == ("decided", 2)
    kinds = [s["kind"] for s in steps_of(client, "CLM-1003")]
    assert kinds.count("error") == 1
    assert len({s["thread_id"] for s in steps_of(client, "CLM-1003")}) == 2


def test_a_claim_that_fails_twice_is_left_for_a_handler(client):
    leave_waiting("CLM-1001", "CLM-1003")
    model = stub(RuntimeError("down"), RuntimeError("still down"), *decide("refer", 0))
    run = dispatch(agent_on(model))

    assert claim_of(client, "CLM-1001")["status"] == "left_for_handler"
    assert claim_of(client, "CLM-1003")["status"] == "decided"
    assert run["status"] == "finished"


def test_a_dispatch_carries_on_stopped_and_signed_off_claims(client, agent_calls):
    leave_waiting("CLM-1001", "CLM-1002")
    saver = InMemorySaver()
    stop_while_working("CLM-1001", saver, call("get_claim"))
    harness.work_claim(
        "CLM-1002", graph_on(stub(*decide("approve", 1350.0)), saver), None
    )
    client.post("/api/claims/CLM-1002/sign-off", json={"handler_id": "HND-01"})
    dispatch(agent_on(stub(record("decline", 0)), saver))

    stopped = claim_of(client, "CLM-1001")
    assert (stopped["status"], stopped["attempts"]) == ("decided", 1)
    signed = claim_of(client, "CLM-1002")
    assert signed["payment"]["signed_off_by"] == "Dana Whitfield"


def test_each_claim_run_has_a_saver_of_its_own(client):
    leave_waiting("CLM-1003", "CLM-1004")
    savers = []

    def new_saver():
        savers.append(InMemorySaver())
        return savers[-1]

    replies = [*decide("refer", 0), *decide("refer", 0)]
    agent = harness.ClaimAgent(stub(*replies), new_saver, "Decide the claim.")
    dispatch(agent, agents=2)
    assert len(savers) == 2
    assert savers[0] is not savers[1]


def test_each_claim_is_tagged_with_its_run(client, traces):
    leave_waiting("CLM-1003")
    run = dispatch(agent_on(stub(*decide("refer", 0))))
    claim = claim_of(client, "CLM-1003")
    [trace] = traces
    assert trace["langfuse_session_id"] == f"CLM-1003:{claim['thread_id']}"
    assert trace["langfuse_tags"] == [run["run_id"]]
    assert {c["run_id"] for c in model_calls_of("CLM-1003")} == {run["run_id"]}


def test_a_claim_worked_on_its_own_has_no_run(client, traces):
    harness.work_claim("CLM-1003", graph_on(stub(*decide("refer", 0))), None)
    assert "langfuse_tags" not in traces[0]
    assert {c["run_id"] for c in model_calls_of("CLM-1003")} == {None}


def test_a_dispatch_finishes_when_its_only_claim_runs_out_of_waits(client):
    leave_waiting("CLM-1003")
    limited = stub(call("get_claim"), rate_limit(), rate_limit(), rate_limit())
    run = dispatch(agent_on(limited))

    assert claim_of(client, "CLM-1003")["status"] == "in_progress"
    assert run["status"] == "finished"


def test_a_claim_signed_off_since_it_was_listed_is_left_to_the_service(
    client, monkeypatch
):
    leave_waiting("CLM-1003")
    resuming = set()
    add_run_claims = api.add_run_claims

    def then_signed_off(run_id, claim_ids):
        resuming.add("CLM-1003")
        return add_run_claims(run_id, claim_ids)

    monkeypatch.setattr(api, "add_run_claims", then_signed_off)
    model = stub()
    run = dispatch(agent_on(model), resuming=resuming)
    assert [c["claim_id"] for c in run["claims"]] == ["CLM-1003"]
    assert model.prompts == []
    assert claim_of(client, "CLM-1003")["status"] == "waiting"


def test_a_claim_decided_since_it_was_listed_is_left_as_it_is(client):
    client.post("/api/claims/CLM-1003/start", json={"thread_id": "t"})
    client.post(
        "/api/claims/CLM-1003/decision",
        json={"decision": "refer", "payout": 0, "section": "S", "reason": "R"},
    )
    run = harness.Run(api.create_dispatch(1, "stub", "none")["run_id"], False)
    model = stub()
    assert harness.work_on("CLM-1003", run, agent_on(model)) == "decided"
    assert model.prompts == []
