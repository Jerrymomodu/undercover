import pytest

from backend.tests.claim_requests import start


def model_call(client, claim_id, run_id=None, **changes):
    body = {
        "run_id": run_id,
        "model": "openai/gpt-6-luna",
        "input_tokens": 1500,
        "output_tokens": 90,
        "cost": 0.0021,
    } | changes
    return client.post(f"/api/claims/{claim_id}/model-calls", json=body)


def work_time(client, claim_id, run_id=None, seconds=12.5):
    body = {"run_id": run_id, "seconds": seconds}
    return client.post(f"/api/claims/{claim_id}/work-times", json=body)


def test_a_model_call_is_recorded_with_no_run(client):
    start(client, "CLM-1001")
    call = model_call(client, "CLM-1001").json()
    assert call["claim_id"] == "CLM-1001"
    assert call["run_id"] is None
    assert (call["input_tokens"], call["output_tokens"]) == (1500, 90)
    assert call["cost"] == 0.0021
    assert call["created_at"]


def test_a_model_call_is_recorded_with_its_run(client):
    run_id = client.post("/api/runs", json={"cap": 1}).json()["run_id"]
    call = model_call(client, "CLM-1001", run_id).json()
    assert call["run_id"] == run_id


def test_a_work_time_is_recorded(client):
    run_id = client.post("/api/runs", json={"cap": 1}).json()["run_id"]
    time = work_time(client, "CLM-1001", run_id).json()
    assert (time["claim_id"], time["run_id"], time["seconds"]) == (
        "CLM-1001",
        run_id,
        12.5,
    )
    assert work_time(client, "CLM-1001").json()["run_id"] is None


def test_an_unknown_claim_or_run(client):
    assert model_call(client, "CLM-9999").status_code == 404
    assert work_time(client, "CLM-9999").status_code == 404
    assert model_call(client, "CLM-1001", "no-such-run").status_code == 404
    assert work_time(client, "CLM-1001", "no-such-run").status_code == 404


@pytest.mark.parametrize(
    "changes", [{"input_tokens": -1}, {"output_tokens": -1}, {"cost": -0.01}]
)
def test_a_negative_model_call_is_refused(client, changes):
    assert model_call(client, "CLM-1001", **changes).status_code == 422


def test_a_negative_work_time_is_refused(client):
    assert work_time(client, "CLM-1001", seconds=-1).status_code == 422
