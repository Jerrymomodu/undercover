from langgraph.checkpoint.memory import InMemorySaver

from agent import api, harness
from agent.tests.records import claim_of, model_calls_of, work_times_of
from agent.tests.stubs import STUB_COST, call, decide, graph_on, record, stub
from backend.tests.claim_requests import sign_off


def test_each_reply_records_its_tokens_and_cost(client):
    model = stub(
        call("get_claim"),
        call("get_policy", policy_id="POL-2001"),
        record("approve", 420.0),
    )
    harness.work_claim("CLM-1001", graph_on(model), None)

    calls = model_calls_of("CLM-1001")
    assert len(calls) == len(model.prompts) == 3
    assert {c["run_id"] for c in calls} == {None}
    assert {(c["model"], c["input_tokens"], c["output_tokens"]) for c in calls} == {
        ("stub", 1200, 80)
    }
    assert sum(c["cost"] for c in calls) == 3 * STUB_COST

    times = work_times_of("CLM-1001")
    assert len(times) == 1
    assert times[0]["run_id"] is None
    assert times[0]["seconds"] >= 0
    assert times[0]["started_at"].endswith("+00:00")


def test_the_wait_for_a_sign_off_is_left_out(client, monkeypatch):
    # Each claim graph run reads the clock twice; the hour passes between them.
    clock = iter([0.0, 5.0, 3605.0, 3607.0])
    monkeypatch.setattr(harness, "perf_counter", lambda: next(clock))
    graph = graph_on(stub(*decide("approve", 1350.0)), InMemorySaver())
    harness.work_claim("CLM-1002", graph, None)
    sign_off(client, "CLM-1002", "HND-01")
    harness.carry_on("CLM-1002", graph, None)

    assert claim_of(client, "CLM-1002")["payment"]["amount"] == 1350.0
    assert [t["seconds"] for t in work_times_of("CLM-1002")] == [5.0, 2.0]


def test_a_failed_attempt_still_records_its_cost_and_time(client):
    model = stub(call("get_claim"), RuntimeError("The provider is down"))
    harness.work_claim("CLM-1004", graph_on(model), None)

    assert claim_of(client, "CLM-1004")["status"] == "waiting"
    assert len(model_calls_of("CLM-1004")) == 1
    assert len(work_times_of("CLM-1004")) == 1


def test_a_run_s_id_goes_with_its_cost_and_time(client):
    run_id = api.create_dispatch(1, "stub", "none")["run_id"]
    harness.work_claim("CLM-1003", graph_on(stub(*decide("refer", 0))), run_id)

    assert {c["run_id"] for c in model_calls_of("CLM-1003")} == {run_id}
    assert [t["run_id"] for t in work_times_of("CLM-1003")] == [run_id]
