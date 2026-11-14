"""Evaluations: the dispatcher and the claim agent working copies of a labelled set."""

import json

import pytest
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent import api, dispatcher, harness, service
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, run_ids
from agent.tests.stubs import agent_on, call, decide, graph_on, record, stub


def evaluate(agent, eval_set="evaluation", tiny=True):
    """Create an evaluation on the backend and work its copies, one at a time."""
    run_id = api.create_evaluation(1, eval_set, tiny, "stub", "none")["run_id"]
    dispatcher.dispatch(harness.Run(run_id, evaluation=True), agent, 1, ())
    return api.get_run(run_id)


def test_an_evaluation_leaves_the_queue_as_it_was(client):
    before = api.list_claims()
    saver = InMemorySaver()
    replies = [
        *decide("approve", 1350.0),
        *[r for _ in range(4) for r in decide("refer", 0)],
    ]
    run = evaluate(agent_on(stub(*replies), saver))

    assert api.list_claims() == before
    assert run["status"] == "finished"
    held, *referred = run["claims"]
    assert held["status"] == "waiting_for_sign_off"
    assert {c["status"] for c in referred} == {"decided"}
    copy = claim_of(client, held["claim_id"])
    assert saver.get_tuple(harness.thread_of(copy)) is None

    evaluation = client.get(f"/api/evaluations/{run['run_id']}").json()
    assert [c["decision"] for c in evaluation["claims"]] == ["approve"] + ["refer"] * 4
    assert evaluation["measures"]["straight_through"] == pytest.approx(1 / 5)


def test_a_dispatch_never_lists_an_evaluation_s_copies(client, monkeypatch):
    leave_waiting("CLM-1001")
    copies = api.create_evaluation(1, "evaluation", True, "stub", "none")["claims"]
    assert {copy["status"] for copy in copies} == {"waiting"}
    worked = []
    monkeypatch.setattr(
        harness, "work_on", lambda c, r, a: worked.append(c) or api.Status.DECIDED
    )
    run_id = api.create_dispatch(1, "stub", "none")["run_id"]
    dispatcher.dispatch(harness.Run(run_id, evaluation=False), agent_on(stub()), 1, ())
    assert worked == ["CLM-1001"]


def test_the_service_starts_an_evaluation(client, serve):
    replies = [r for _ in range(5) for r in decide("refer", 0)]
    agent = serve(agent_on(stub(*replies)))
    body = {"agents": 2, "eval_set": "held_out", "tiny": True}
    assert agent.post("/api/evaluations", json=body).status_code == 202

    [run_id] = run_ids()
    run = api.get_run(run_id)
    assert (run["kind"], run["eval_set"], run["tiny"], run["agents"]) == (
        "evaluation",
        "held_out",
        True,
        2,
    )
    assert (run["model"], run["reasoning_effort"]) == ("openai/gpt-6-luna", "low")
    assert run["status"] == "finished"
    assert {c["status"] for c in run["claims"]} == {"decided"}


def test_an_evaluation_waits_its_turn(serve):
    agent = serve(agent_on(stub()))
    service.running.acquire()
    try:
        body = {"agents": 2, "eval_set": "evaluation", "tiny": False}
        response = agent.post("/api/evaluations", json=body)
    finally:
        service.running.release()
    assert response.status_code == 409


def test_the_claim_agent_works_a_copy_as_it_would_any_claim(client):
    copy = api.create_evaluation(1, "held_out", True, "stub", "none")["claims"][0]
    model = stub(call("get_claim"), record("refer", 0))
    harness.work_claim(copy["claim_id"], graph_on(model), None)
    result = next(m for m in model.prompts[-1] if isinstance(m, ToolMessage))
    shown = json.loads(result.text)
    assert shown["claim_id"] == copy["claim_id"]
    assert "copy_of" not in shown
    assert "evaluation_id" not in shown
