import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent import api, harness, service
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, run_ids, steps_of
from agent.tests.stubs import agent_on, decide, graph_on, stub
from api_rules import rule_breaks


def resume(agent, claim_id):
    return agent.post(f"/api/claims/{claim_id}/resume")


def test_the_service_follows_the_api_rules():
    assert rule_breaks(service.app.openapi()) == []


def test_health():
    assert TestClient(service.app).get("/api/health").json() == {"status": "ok"}


def test_a_sign_off_picks_the_claim_up_and_pays_it_once(
    client, serve, agent_calls, traces
):
    model, saver = stub(*decide("approve", 1350.0)), InMemorySaver()
    harness.work_claim("CLM-1002", graph_on(model, saver), None)
    signed = client.post("/api/claims/CLM-1002/sign-off", json={"handler_id": "HND-01"})
    assert agent_calls == ["/api/claims/CLM-1002/resume"]

    agent = serve(agent_on(model, saver))
    response = resume(agent, "CLM-1002")
    assert response.status_code == 202
    claim = claim_of(client, "CLM-1002")
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 1350.0
    assert claim["payment"]["signed_off_by"] == "Dana Whitfield"
    signed_off_at = signed.json()["decision"]["signed_off_at"]
    assert claim["payment"]["signed_off_at"] == signed_off_at
    assert len(model.prompts) == 2
    session = f"CLM-1002:{claim['thread_id']}"
    assert [(t["langfuse_session_id"], t["langfuse_trace_name"]) for t in traces] == [
        (session, "Work claim"),
        (session, "Carry on"),
    ]

    assert resume(agent, "CLM-1002").status_code == 409
    assert claim_of(client, "CLM-1002")["payment"] == claim["payment"]


def test_a_claim_waiting_for_sign_off_is_not_picked_up(client, serve):
    model, saver = stub(*decide("approve", 1350.0)), InMemorySaver()
    harness.work_claim("CLM-1002", graph_on(model, saver), None)
    before = steps_of(client, "CLM-1002")
    response = resume(serve(agent_on(model, saver)), "CLM-1002")
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Claim CLM-1002 has no sign-off waiting to be paid"
    )
    assert claim_of(client, "CLM-1002")["status"] == "waiting_for_sign_off"
    assert steps_of(client, "CLM-1002") == before


def test_a_claim_in_progress_without_a_sign_off_is_left_to_its_agent(client, serve):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "working"})
    response = resume(serve(agent_on(stub())), "CLM-1001")
    assert response.status_code == 409
    claim = claim_of(client, "CLM-1001")
    assert (claim["status"], claim["attempts"]) == ("in_progress", 1)
    assert steps_of(client, "CLM-1001") == []


def test_an_unknown_claim(serve):
    response = resume(serve(agent_on(stub())), "CLM-9999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Claim CLM-9999 not found"


def start_dispatch(agent, agents):
    return agent.post("/api/dispatches", json={"agents": agents})


def test_a_dispatch_starts_and_works_the_queue(client, serve, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    leave_waiting("CLM-1003")
    response = start_dispatch(serve(agent_on(stub(*decide("refer", 0)))), 3)
    assert response.status_code == 202

    [run_id] = run_ids()
    created = api.get_run(run_id)
    assert (created["kind"], created["agents"], created["status"]) == (
        "dispatch",
        3,
        "finished",
    )
    assert (created["model"], created["reasoning_effort"]) == (
        "openrouter/free",
        "none",
    )
    assert [c["claim_id"] for c in created["claims"]] == ["CLM-1003"]
    assert claim_of(client, "CLM-1003")["status"] == "decided"
    assert not service.running.locked()


def test_a_second_start_is_refused_while_a_run_is_going(serve):
    agent = serve(agent_on(stub()))
    service.running.acquire()
    try:
        response = start_dispatch(agent, 3)
    finally:
        service.running.release()
    assert response.status_code == 409
    assert response.json()["detail"] == "A dispatch or evaluation is already running"


@pytest.mark.parametrize("agents", [0, 26])
def test_n_is_from_1_to_25(serve, agents):
    assert start_dispatch(serve(agent_on(stub())), agents).status_code == 422


def test_on_starting_the_service_stops_runs_left_running(client, monkeypatch):
    run_id = api.create_dispatch(3, "stub", "low")["run_id"]
    tries = []
    health = api.health

    def backend_starting():
        tries.append(1)
        if len(tries) == 1:
            raise httpx.ConnectError("The backend is starting")
        return health()

    monkeypatch.setattr(api, "health", backend_starting)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: None)
    service.stop_earlier_runs()
    assert len(tries) == 2
    assert api.get_run(run_id)["status"] == "stopped"


def test_the_service_gives_up_on_a_backend_that_never_answers(monkeypatch):
    def down():
        raise httpx.ConnectError("Nothing is listening")

    monkeypatch.setattr(api, "health", down)
    monkeypatch.setattr(api.time, "sleep", lambda seconds: None)
    with pytest.raises(httpx.ConnectError):
        api.wait_for_backend(0)


def test_a_dispatch_that_fails_is_stopped_and_lets_another_start(
    client, serve, monkeypatch
):
    def broken(*args):
        raise RuntimeError("The backend refused the list")

    monkeypatch.setattr(service, "dispatch", broken)
    agent = serve(agent_on(stub()))
    with pytest.raises(RuntimeError):
        start_dispatch(agent, 3)
    [run_id] = run_ids()
    assert api.get_run(run_id)["status"] == "stopped"
    assert not service.running.locked()
