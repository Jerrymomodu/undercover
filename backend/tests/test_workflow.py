from contextlib import closing

import pytest

from backend import db

CLAIM = "/api/claims/CLM-1001"
BLOCKED = "A payout over $1,000.00 needs a handler's sign-off."


def start(client):
    response = client.post(f"{CLAIM}/start", json={"thread_id": "thread-1"})
    assert response.status_code == 200
    return response.json()


def decide(client, decision, payout):
    return client.post(
        f"{CLAIM}/decision",
        json={
            "decision": decision,
            "payout": payout,
            "reason": "The reason for the decision.",
            "policy_section": "3. Trip Delay",
        },
    )


def pay(client, amount):
    return client.post(f"{CLAIM}/payment", json={"amount": amount})


def sign_off(client, handler_id="HND-01"):
    return client.post(f"{CLAIM}/sign-off", json={"handler_id": handler_id})


def test_start_puts_a_claim_in_progress(client):
    state = start(client)
    assert state == {
        "claim_id": "CLM-1001",
        "status": "in_progress",
        "decision": None,
        "sign_off": None,
        "payment": None,
    }
    steps = client.get(f"{CLAIM}/steps").json()
    assert [(s["thread_id"], s["kind"]) for s in steps] == [("thread-1", "note")]


def test_start_twice_is_a_conflict(client):
    start(client)
    response = client.post(f"{CLAIM}/start", json={"thread_id": "thread-2"})
    assert response.status_code == 409
    assert response.json() == {"detail": "Claim CLM-1001 is in progress."}


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_decline_or_refer_decides_the_claim(client, decision):
    start(client)
    state = decide(client, decision, 0).json()
    assert state["status"] == "decided"
    assert state["decision"]["decision"] == decision
    assert state["decision"]["reason"] == "The reason for the decision."
    assert state["decision"]["policy_section"] == "3. Trip Delay"
    assert pay(client, 1).status_code == 409


def test_approve_and_pay_within_the_limit(client):
    start(client)
    assert decide(client, "approve", 420).json()["status"] == "decided"
    state = pay(client, 420).json()
    assert state["payment"]["amount"] == 420.0
    summary = client.get("/api/claims").json()[0]
    assert (summary["decision"], summary["payout"]) == ("approve", 420.0)


def test_approve_at_exactly_the_limit_needs_no_sign_off(client):
    start(client)
    assert decide(client, "approve", 1000).json()["status"] == "decided"
    assert pay(client, 1000).status_code == 200


def test_payment_over_the_limit_waits_for_a_sign_off(client):
    start(client)
    assert decide(client, "approve", 1250).json()["status"] == "awaiting_sign_off"

    response = pay(client, 1250)
    assert response.status_code == 403
    assert response.json() == {"detail": BLOCKED}
    claim = client.get(CLAIM).json()
    assert claim["status"] == "awaiting_sign_off"
    assert claim["payment"] is None

    state = sign_off(client).json()
    assert state["status"] == "decided"
    assert state["sign_off"]["handler_name"] == "Dana Whitfield"
    assert state["payment"]["amount"] == 1250.0
    assert pay(client, 1250).status_code == 409


def test_payment_must_match_the_approved_payout(client):
    start(client)
    decide(client, "approve", 420)
    response = pay(client, 500)
    assert response.status_code == 409
    assert response.json() == {"detail": "The approved payout is $420.00."}


def test_a_claim_is_paid_only_once(client):
    start(client)
    decide(client, "approve", 420)
    pay(client, 420)
    response = pay(client, 420)
    assert response.status_code == 409
    assert response.json() == {"detail": "Claim CLM-1001 has already been paid."}


def test_an_undecided_claim_cannot_be_paid(client):
    assert pay(client, 420).status_code == 409


def test_deciding_needs_the_claim_in_progress(client):
    response = decide(client, "approve", 420)
    assert response.status_code == 409
    assert response.json() == {"detail": "Claim CLM-1001 is waiting."}
    start(client)
    decide(client, "decline", 0)
    assert decide(client, "decline", 0).status_code == 409


def test_payout_must_match_the_decision(client):
    start(client)
    assert decide(client, "approve", 0).status_code == 422
    assert decide(client, "decline", 100).status_code == 422
    assert decide(client, "refer", 100).status_code == 422
    assert decide(client, "approve", -5).status_code == 422


def test_payout_is_kept_to_the_cent(client):
    start(client)
    state = decide(client, "approve", 123.456).json()
    assert state["decision"]["payout"] == 123.46


def test_sign_off_needs_a_claim_waiting_for_it(client):
    response = sign_off(client)
    assert response.status_code == 409
    start(client)
    decide(client, "approve", 420)
    assert sign_off(client).status_code == 409


def test_sign_off_needs_a_known_handler(client):
    start(client)
    decide(client, "approve", 1250)
    response = sign_off(client, "HND-99")
    assert response.status_code == 404
    assert response.json() == {"detail": "There is no handler HND-99."}


def test_sign_off_needs_a_handler_who_can_approve_over_the_limit(client):
    with closing(db.connect()) as connection, connection:
        connection.execute(
            "UPDATE handlers SET can_approve_over_limit = 0 WHERE handler_id = 'HND-02'"
        )
    start(client)
    decide(client, "approve", 1250)
    response = sign_off(client, "HND-02")
    assert response.status_code == 403
    assert client.get(CLAIM).json()["status"] == "awaiting_sign_off"


def test_release_puts_a_claim_back_in_the_queue(client):
    start(client)
    assert client.post(f"{CLAIM}/release").json()["status"] == "waiting"
    assert client.post(f"{CLAIM}/release").status_code == 409


def test_steps_are_recorded_in_order(client):
    start(client)
    for kind, text in [("tool_call", "get_claim"), ("reply", "Declined.")]:
        response = client.post(
            f"{CLAIM}/steps", json={"thread_id": "thread-1", "kind": kind, "text": text}
        )
        assert response.status_code == 200
    steps = client.get(f"{CLAIM}/steps").json()
    assert [s["kind"] for s in steps] == ["note", "tool_call", "reply"]
    assert steps[-1]["text"] == "Declined."


def test_steps_need_a_known_claim_and_kind(client):
    step = {"thread_id": "thread-1", "kind": "note", "text": "Hello"}
    assert client.post("/api/claims/CLM-9999/steps", json=step).status_code == 404
    assert client.get("/api/claims/CLM-9999/steps").status_code == 404
    step["kind"] = "shout"
    assert client.post(f"{CLAIM}/steps", json=step).status_code == 422
