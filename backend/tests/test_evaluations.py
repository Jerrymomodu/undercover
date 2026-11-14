import json

import httpx
import pytest
from sqlalchemy import func, select

from backend import scoring
from backend.database import EVALS, answer_key, engine, held_out_claims, load
from backend.models import Run, RunSummary
from backend.tests.claim_requests import decide, sign_off, start
from backend.tests.runs import create_dispatch, create_evaluation


def count(table):
    with engine().connect() as db:
        return db.execute(select(func.count()).select_from(table)).scalar_one()


def test_seeding_keeps_the_answer_key_and_the_held_out_claims_apart(client):
    assert count(held_out_claims) == 25
    assert count(answer_key) == 50
    queue = client.get("/api/claims").json()
    assert len(queue) == 25
    assert all(claim["claim_id"] < "CLM-1100" for claim in queue)


def test_an_evaluation_works_copies_that_stay_out_of_the_queue(client):
    before = client.get("/api/claims").json()
    run = create_evaluation(client, "held_out", tiny=True).json()
    assert (run["kind"], run["eval_set"], run["tiny"]) == (
        "evaluation",
        "held_out",
        True,
    )
    copies = [claim["claim_id"] for claim in run["claims"]]
    assert len(copies) == 5
    assert all(c.startswith(f"E{run['number']}-CLM-11") for c in copies)
    assert {c["status"] for c in run["claims"]} == {"waiting"}

    copy = client.get(f"/api/claims/{copies[0]}").json()
    assert copy["claim_id"] == copies[0]
    assert copy["evaluation_id"] == run["run_id"]
    assert copies[0].endswith(copy["copy_of"])
    assert client.get("/api/claims").json() == before


def test_an_evaluation_of_the_whole_evaluation_set(client):
    run = create_evaluation(client, "evaluation", tiny=False).json()
    assert len(run["claims"]) == 25
    first = client.get(f"/api/claims/{run['claims'][0]['claim_id']}").json()
    assert first["copy_of"] == "CLM-1001"


def test_a_copy_holds_nothing_from_the_handlers_decisions(client):
    run = create_evaluation(client, "held_out", tiny=True).json()
    reasons = {
        d["claim_id"]: d["reason"] for d in load("held_out_decisions.json", EVALS)
    }
    for claim in run["claims"]:
        response = client.get(f"/api/claims/{claim['claim_id']}")
        copy = response.json()
        assert set(copy) >= {"claim_id", "story", "decision", "copy_of"}
        assert "handler_decision" not in copy
        assert reasons[copy["copy_of"]] not in response.text


def test_nobody_can_sign_off_a_copy(client):
    run = create_evaluation(client, "held_out", tiny=False).json()
    copy = run["claims"][0]["claim_id"]
    start(client, copy)
    decide(client, copy, "approve", 1350)
    response = sign_off(client, copy, "HND-01")
    assert response.status_code == 409
    assert response.json()["detail"] == f"Claim {copy} is an evaluation's copy"
    claim = client.get(f"/api/claims/{copy}").json()
    assert claim["status"] == "waiting_for_sign_off"
    assert claim["decision"]["signed_off_by"] is None


def test_starting_an_evaluation_reaches_the_agent_s_service(client, agent_answers):
    sent = []

    def accept(request: httpx.Request) -> httpx.Response:
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(202, json={"status": "accepted"})

    agent_answers(accept)
    body = {"agents": 4, "eval_set": "held_out", "tiny": True}
    response = client.post("/api/evaluations/start", json=body)
    assert response.status_code == 202
    assert sent == [("/api/evaluations", body)]


@pytest.mark.parametrize(
    "body",
    [
        {"agents": 0, "eval_set": "held_out", "tiny": True},
        {"agents": 4, "eval_set": "queue", "tiny": True},
    ],
)
def test_an_evaluation_needs_n_and_a_labelled_set(client, body):
    assert client.post("/api/evaluations/start", json=body).status_code == 422


def test_the_scoreboard_lists_evaluations_newest_first(client):
    older = create_evaluation(client, "held_out", tiny=True).json()["run_id"]
    create_dispatch(client)
    newer = create_evaluation(client, "evaluation", tiny=True).json()["run_id"]
    listed = client.get("/api/evaluations").json()
    assert [e["run"]["run_id"] for e in listed] == [newer, older]
    assert listed[0]["measures"]["straight_through"] == 0
    assert listed[0]["measures"]["run_seconds"] is None


def test_an_evaluation_s_page_shows_the_handler_beside_the_agent(client):
    run = create_evaluation(client, "evaluation", tiny=False).json()
    first = run["claims"][0]["claim_id"]
    start(client, first)
    decide(client, first, "approve", 420)
    client.post(f"/api/runs/{run['run_id']}/finish")

    evaluation = client.get(f"/api/evaluations/{run['run_id']}").json()
    claim = evaluation["claims"][0]
    assert (claim["claim_id"], claim["copy_of"]) == (first, "CLM-1001")
    assert (claim["handler_decision"], claim["handler_payout"]) == ("approve", 420)
    assert (claim["decision"], claim["payout"], claim["right"]) == (
        "approve",
        420,
        True,
    )
    assert evaluation["claims"][1]["decision"] is None
    assert evaluation["measures"]["run_seconds"] is not None


def test_a_dispatch_is_not_an_evaluation(client):
    run_id = create_dispatch(client).json()["run_id"]
    assert client.get(f"/api/evaluations/{run_id}").status_code == 404


def outcome(handler, payout, decision, agent_payout, seconds):
    """One scored claim, as the scoring query gives it."""
    return scoring.score(
        {
            "claim_id": "E1-X",
            "copy_of": "X",
            "handler_decision": handler,
            "handler_payout": payout,
            "decision": decision,
            "payout": agent_payout,
            "reason": None,
            "cost": 0.0,
            "seconds": seconds,
        }
    )


def test_the_measures_match_ones_worked_out_by_hand():
    scored = [
        outcome("approve", 420, "approve", 420, 10),  # right
        outcome("approve", 1000, "approve", 950, 20),  # right, $50 short
        outcome("approve", 500, "decline", 0, 30),  # wrongful decline, $1,500
        outcome("decline", 0, "approve", 800, 40),  # wrongful approval, $800
        outcome("approve", 300, "refer", 0, 50),  # needless referral, $50
        outcome("decline", 0, None, None, 60),  # undecided: a referral, $50
    ]
    assert [c.right for c in scored] == [True, False, False, False, False, False]
    assert [c.mistake_cost for c in scored] == [0, 50, 1500, 800, 50, 50]
    run = Run(
        run_id="r",
        number=1,
        kind="evaluation",
        agents=3,
        status="finished",
        started_at="2026-11-14T10:00:00+00:00",
        finished_at="2026-11-14T10:02:00+00:00",
        eval_set="evaluation",
        tiny=False,
        model="openai/gpt-6-luna",
        reasoning_effort="low",
        claims=[],
        summary=RunSummary(
            approved=0,
            declined=0,
            referred=0,
            waiting_for_sign_off=[],
            left_for_handler=[],
            in_progress=[],
            waiting=[],
        ),
        cost=0.06,
        agent_seconds=210,
    )
    measures = scoring.measures(run, scored)
    assert measures.decision_accuracy == pytest.approx(2 / 6)
    assert measures.accuracy == pytest.approx(1 / 6)
    assert measures.cost_of_mistakes == 2450
    assert measures.straight_through == pytest.approx(4 / 6)
    assert measures.cost_per_claim == pytest.approx(0.01)
    assert measures.seconds_per_claim == 35
    assert measures.run_seconds == 120


def test_a_dispatch_s_claims_are_never_an_evaluation_s(client):
    evaluation = create_evaluation(client, "held_out", tiny=True).json()
    copy = evaluation["claims"][0]["claim_id"]
    path = f"/api/runs/{evaluation['run_id']}/claims"
    refused = client.put(path, json={"claim_ids": ["CLM-1001"]})
    assert refused.status_code == 409
    assert refused.json()["detail"] == f"Run {evaluation['run_id']} is not a dispatch"
    assert len(client.get(f"/api/runs/{evaluation['run_id']}").json()["claims"]) == 5

    dispatch = create_dispatch(client).json()["run_id"]
    response = client.put(f"/api/runs/{dispatch}/claims", json={"claim_ids": [copy]})
    assert response.status_code == 409
    assert response.json()["detail"] == f"Claim {copy} is an evaluation's copy"
