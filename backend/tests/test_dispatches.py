import json

import httpx
import pytest

from backend.tests.claim_requests import (
    decide,
    fail,
    model_call,
    pay,
    start,
    work_time,
)
from backend.tests.runs import create_dispatch


def start_dispatch(client, agents=5):
    return client.post("/api/dispatch/start", json={"agents": agents})


def test_starting_a_dispatch_reaches_the_agent_s_service(client, agent_answers):
    sent = []

    def accept(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(202, json={"status": "accepted"})

    agent_answers(accept)
    response = start_dispatch(client, 5)
    assert response.status_code == 202
    assert sent == [("/api/dispatches", {"agents": 5})]


def test_a_refusal_from_the_agent_s_service_is_passed_on(client, agent_answers):
    busy = {"detail": "A dispatch or evaluation is already running"}
    agent_answers(lambda request: httpx.Response(409, json=busy))
    response = start_dispatch(client)
    assert response.status_code == 409
    assert response.json() == busy


def test_starting_without_the_agent_s_service(client, agent_answers):
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    agent_answers(unreachable)
    response = start_dispatch(client)
    assert response.status_code == 503
    assert response.json()["detail"] == "The agent's service isn't running"


@pytest.mark.parametrize("agents", [0, 26])
def test_n_is_from_1_to_25(client, agents):
    assert start_dispatch(client, agents).status_code == 422


def test_no_dispatch_yet(client):
    response = client.get("/api/dispatches/latest")
    assert response.status_code == 200
    assert response.json() is None


def test_the_summary_is_built_from_the_records(client):
    run_id = create_dispatch(client).json()["run_id"]
    ids = ["CLM-1001", "CLM-1002", "CLM-1003", "CLM-1004", "CLM-1005", "CLM-1006"]
    client.put(f"/api/runs/{run_id}/claims", json={"claim_ids": [*ids, "CLM-1007"]})
    for claim_id in ids:
        start(client, claim_id)
    decide(client, "CLM-1001", "approve", 420)
    pay(client, "CLM-1001", 420)
    decide(client, "CLM-1002", "approve", 1350)
    decide(client, "CLM-1003", "decline", 0)
    decide(client, "CLM-1004", "refer", 0)
    fail(client, "CLM-1005")
    start(client, "CLM-1005")
    fail(client, "CLM-1005")
    client.post(f"/api/runs/{run_id}/finish")

    run = client.get("/api/dispatches/latest").json()
    assert run["run_id"] == run_id
    assert run["summary"] == {
        "approved": 2,
        "declined": 1,
        "referred": 1,
        "waiting_for_sign_off": [{"claim_id": "CLM-1002", "payout": 1350}],
        "left_for_handler": ["CLM-1005"],
        "in_progress": ["CLM-1006"],
        "waiting": ["CLM-1007"],
    }


def test_a_dispatch_s_cost_and_time_are_its_own(client):
    run_id = create_dispatch(client).json()["run_id"]
    other = create_dispatch(client).json()["run_id"]
    model_call(client, "CLM-1001", run_id, cost=0.004)
    model_call(client, "CLM-1002", run_id, cost=0.006)
    model_call(client, "CLM-1001", other, cost=0.5)
    model_call(client, "CLM-1001", None, cost=0.25)
    work_time(client, "CLM-1001", run_id, seconds=12)
    work_time(client, "CLM-1002", run_id, seconds=8.5)
    work_time(client, "CLM-1001", None, seconds=100)

    run = client.get(f"/api/runs/{run_id}").json()
    assert run["cost"] == pytest.approx(0.01)
    assert run["agent_seconds"] == 20.5
    assert client.get("/api/dispatches/latest").json()["run_id"] == other
