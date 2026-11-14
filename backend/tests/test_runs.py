import pytest

from backend.tests.claim_requests import decide, start
from backend.tests.runs import create_dispatch


def add_claims(client, run_id, *claim_ids):
    return client.put(f"/api/runs/{run_id}/claims", json={"claim_ids": list(claim_ids)})


def test_create_a_dispatch(client):
    run = create_dispatch(client, agents=3).json()
    assert (run["kind"], run["agents"], run["status"]) == ("dispatch", 3, "running")
    assert (run["model"], run["reasoning_effort"]) == ("openai/gpt-6-luna", "low")
    assert (run["eval_set"], run["tiny"], run["finished_at"]) == (None, None, None)
    assert run["started_at"]
    assert run["claims"] == []
    assert client.get(f"/api/runs/{run['run_id']}").json() == run


def test_runs_are_numbered_in_order(client):
    first = create_dispatch(client).json()
    second = create_dispatch(client).json()
    assert second["number"] == first["number"] + 1


@pytest.mark.parametrize("agents", [0, 26])
def test_n_is_from_1_to_25(client, agents):
    assert create_dispatch(client, agents=agents).status_code == 422


def test_a_dispatch_records_its_claims_and_where_each_stands(client):
    run_id = create_dispatch(client).json()["run_id"]
    start(client, "CLM-1003")
    decide(client, "CLM-1003", "refer", 0)
    run = add_claims(client, run_id, "CLM-1003", "CLM-1001").json()
    assert run["claims"] == [
        {"claim_id": "CLM-1003", "status": "decided", "decision": "refer", "payout": 0},
        {"claim_id": "CLM-1001", "status": "waiting", "decision": None, "payout": None},
    ]
    run = add_claims(client, run_id, "CLM-1002").json()
    assert [c["claim_id"] for c in run["claims"]] == ["CLM-1002"]


def test_claims_for_an_unknown_run_or_claim(client):
    assert add_claims(client, "no-such-run", "CLM-1001").status_code == 404
    run_id = create_dispatch(client).json()["run_id"]
    assert add_claims(client, run_id, "CLM-9999").status_code == 404
    assert client.get("/api/runs/no-such-run").status_code == 404


def test_finish_a_run(client):
    run_id = create_dispatch(client).json()["run_id"]
    run = client.post(f"/api/runs/{run_id}/finish").json()
    assert run["status"] == "finished"
    assert run["finished_at"]
    again = client.post(f"/api/runs/{run_id}/finish")
    assert again.status_code == 409
    assert again.json()["detail"] == f"Run {run_id} is not running"
    assert add_claims(client, run_id, "CLM-1001").status_code == 409


def test_stop_the_runs_left_running(client):
    finished = create_dispatch(client).json()["run_id"]
    client.post(f"/api/runs/{finished}/finish")
    running = create_dispatch(client).json()["run_id"]
    stopped = client.post("/api/runs/stop").json()
    assert [run["run_id"] for run in stopped] == [running]
    assert client.get(f"/api/runs/{running}").json()["status"] == "stopped"
    assert client.get(f"/api/runs/{finished}").json()["status"] == "finished"
    assert client.post("/api/runs/stop").json() == []
