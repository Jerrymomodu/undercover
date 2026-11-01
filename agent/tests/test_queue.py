import sqlite3
from contextlib import closing

import pytest
from langchain_core.messages import AIMessage

from agent import __main__ as cli
from agent import queue
from agent.queue import QueueRun, queue_tools, work_queue
from agent.tests.test_agent import BrokenModel, StubModel, call, script

CLAIMS = {
    "CLM-1001": ("POL-2001", "CUS-3001", "approve", 420.0),
    "CLM-1002": ("POL-2002", "CUS-3002", "approve", 1350.0),
    "CLM-1003": ("POL-2003", "CUS-3003", "refer", 0),
}


@pytest.fixture
def three_waiting(database):
    """Leave only CLM-1001, CLM-1002 and CLM-1003 waiting in the queue."""
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE claims SET status = 'decided'"
            " WHERE claim_id NOT IN ('CLM-1001', 'CLM-1002', 'CLM-1003')"
        )


def deciding(claim_id):
    """A claim agent that decides the claim, paying an approval."""
    policy_id, customer_id, decision, payout = CLAIMS[claim_id]
    extra = []
    if decision == "approve":
        extra = [call("pay_claim", claim_id=claim_id, amount=payout)]
    return script(claim_id, policy_id, customer_id, decision, payout, *extra)


def failing():
    return BrokenModel(messages=iter([]))


def models(**plans):
    """Give each claim its claim agents in turn, deciding by default."""
    queues = {
        claim_id.replace("_", "-"): list(plan) for claim_id, plan in plans.items()
    }

    def pick(claim_id):
        planned = queues.get(claim_id)
        return planned.pop(0) if planned else deciding(claim_id)

    return pick


def todos(*items):
    return call(
        "write_todos",
        todos=[{"content": content, "status": status} for content, status in items],
    )


def queue_agent(*steps):
    return StubModel(messages=iter([*steps, AIMessage(content="All done.")]))


def work(*claim_ids):
    return [call("work_claim", claim_id=claim_id) for claim_id in claim_ids]


def finish(summary="Worked the claims."):
    return call("finish_run", summary=summary)


def current_run(client):
    return client.get("/api/runs/current").json()


def statuses(client):
    return {c["claim_id"]: c["status"] for c in client.get("/api/claims").json()}


def test_the_queue_agents_tools(database):
    run = QueueRun(None, lambda _: None)
    names = [t.name for t in queue_tools(run)]
    assert names == ["list_claims", "write_todos", "work_claim", "finish_run"]


def test_a_whole_run(capsys, client, three_waiting):
    stub = queue_agent(
        call("list_claims"),
        todos(
            ("CLM-1001", "in_progress"), ("CLM-1002", "to_do"), ("CLM-1003", "to_do")
        ),
        *work("CLM-1001"),
        todos(("CLM-1001", "done"), ("CLM-1002", "in_progress"), ("CLM-1003", "to_do")),
        *work("CLM-1002", "CLM-1003"),
        todos(("CLM-1001", "done"), ("CLM-1002", "done"), ("CLM-1003", "done")),
        finish("Worked 3 claims: 2 approved and 1 referred."),
    )
    summary = work_queue(None, stub, models())

    assert summary == "Worked 3 claims: 2 approved and 1 referred."
    assert stub.prompts[0][1].content == "Work the whole queue."
    listing = stub.prompts[1][-1].text
    assert listing.splitlines()[0] == (
        "CLM-1001  trip_delay  $420.00  submitted 2026-06-24"
    )
    assert len(listing.splitlines()) == 3
    assert stub.prompts[2][-1].text == "The to-do list is saved."
    assert stub.prompts[3][-1].text == "CLM-1001  approve  $420.00  paid"

    run = current_run(client)
    assert run["cap"] is None
    assert run["summary"] == summary
    assert run["finished_at"] is not None
    assert [t["status"] for t in run["todos"]] == ["done", "done", "done"]
    assert statuses(client)["CLM-1001"] == "decided"
    assert statuses(client)["CLM-1002"] == "waiting_for_sign_off"
    assert capsys.readouterr().out.splitlines() == [
        "CLM-1001  approve  $420.00  paid",
        "CLM-1002  approve  $1,350.00  waiting for sign-off",
        "CLM-1003  refer  $0.00",
        summary,
    ]


def test_the_cap(client, three_waiting):
    stub = queue_agent(*work("CLM-1001", "CLM-1002", "CLM-1003"), finish())
    work_queue(2, stub, models())

    assert stub.prompts[0][1].content == "Work up to 2 claims."
    assert stub.prompts[3][-1].text == (
        "CLM-1003  not started: this run's cap of 2 claims is reached"
    )
    assert stub.prompts[4][-1].text == "The run is finished."
    assert statuses(client)["CLM-1003"] == "waiting"
    assert current_run(client)["cap"] == 2


def test_a_failed_claim_does_not_stop_the_run(client, three_waiting):
    stub = queue_agent(*work("CLM-1001", "CLM-1002", "CLM-1003"), finish())
    work_queue(3, stub, models(CLM_1001=[failing()]))

    assert "Back in the queue" in stub.prompts[1][-1].text
    found = statuses(client)
    assert found["CLM-1001"] == "waiting"
    assert found["CLM-1002"] == "waiting_for_sign_off"
    assert found["CLM-1003"] == "decided"
    assert current_run(client)["summary"] == "Worked the claims."


def test_a_failed_claim_is_tried_again(client, three_waiting):
    stub = queue_agent(*work("CLM-1001", "CLM-1001", "CLM-1002"), finish())
    work_queue(1, stub, models(CLM_1001=[failing()]))

    assert stub.prompts[2][-1].text == "CLM-1001  approve  $420.00  paid"
    assert stub.prompts[3][-1].text.endswith("cap of 1 claims is reached")
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["failures"] == 1


def test_a_claim_that_fails_twice_is_left_for_a_handler(client, three_waiting):
    stub = queue_agent(
        *work("CLM-1001", "CLM-1001"),
        todos(("CLM-1001", "for_handler")),
        finish(),
    )
    work_queue(1, stub, models(CLM_1001=[failing(), failing()]))

    assert "Left for a handler after 2 failed tries" in stub.prompts[2][-1].text
    assert statuses(client)["CLM-1001"] == "left_for_handler"
    assert current_run(client)["todos"] == [
        {"content": "CLM-1001", "status": "for_handler"}
    ]


def test_finishing_checks_for_missed_claims(client, three_waiting):
    stub = queue_agent(
        *work("CLM-1001"),
        finish(),
        *work("CLM-1002", "CLM-1003"),
        finish(),
    )
    work_queue(None, stub, models())

    assert stub.prompts[2][-1].text == (
        "Not finished: 2 claims are still waiting within the run's cap:"
        " CLM-1002, CLM-1003. Work them, then finish."
    )
    assert stub.prompts[5][-1].text == "The run is finished."
    assert "waiting" not in statuses(client).values()


def test_finishing_ticks_off_the_summary(client, three_waiting):
    stub = queue_agent(
        *work("CLM-1001"),
        todos(
            ("CLM-1001", "done"),
            ("CLM-1002", "to_do"),
            ("Write the summary", "in_progress"),
        ),
        finish(),
    )
    work_queue(1, stub, models())
    assert [t["status"] for t in current_run(client)["todos"]] == [
        "done",
        "to_do",
        "done",
    ]


def test_a_run_that_stops(client, three_waiting):
    summary = work_queue(None, BrokenModel(messages=iter([])), models())
    assert summary == "The run stopped: RuntimeError: The model provider is unavailable"
    assert current_run(client)["summary"] == summary
    assert "in_progress" not in statuses(client).values()


def test_a_run_the_agent_never_finishes(client, three_waiting):
    summary = work_queue(None, queue_agent(*work("CLM-1001")), models())
    assert summary == "The run ended before the agent finished it."
    assert current_run(client)["finished_at"] is not None


def test_todos_after_the_run_has_finished_are_refused(client, three_waiting):
    stub = queue_agent(*work("CLM-1001"), finish(), todos(("CLM-1001", "done")))
    work_queue(1, stub, models())
    assert stub.prompts[3][-1].text.startswith("Refused with status 409")


def test_claims_left_in_progress_are_released_when_a_run_starts(client, three_waiting):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "old-run"})
    work_queue(1, queue_agent(finish()), models())
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "waiting"
    assert claim["failures"] == 1
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert (steps[-1]["kind"], steps[-1]["content"]) == ("error", queue.STUCK)


def test_command_line(monkeypatch):
    runs = []
    monkeypatch.setattr(cli, "work_queue", runs.append)
    cli.main(["--cap", "5"])
    cli.main([])
    assert runs == [5, None]
    with pytest.raises(SystemExit):
        cli.main(["--cap", "0"])
