from backend.tests.test_workflow import decide, pay, start


def release(client, claim_id, reason="The model timed out"):
    return client.post(f"/api/claims/{claim_id}/release", json={"reason": reason})


def test_first_failure_goes_back_in_the_queue(client):
    start(client, "CLM-1005")
    claim = release(client, "CLM-1005").json()
    assert claim["status"] == "waiting"
    assert claim["failures"] == 1
    steps = client.get("/api/claims/CLM-1005/steps").json()
    assert [(s["kind"], s["content"]) for s in steps] == [
        ("error", "The model timed out")
    ]
    queue = {c["claim_id"]: c for c in client.get("/api/claims").json()}
    assert queue["CLM-1005"]["failures"] == 1


def test_second_failure_is_left_for_a_handler(client):
    start(client, "CLM-1005")
    release(client, "CLM-1005")
    start(client, "CLM-1005")
    claim = release(client, "CLM-1005", "Too many model calls").json()
    assert claim["status"] == "left_for_handler"
    assert claim["failures"] == 2
    assert start(client, "CLM-1005").status_code == 409
    assert release(client, "CLM-1005").status_code == 409


def test_release_needs_an_undecided_claim_in_progress(client):
    assert release(client, "CLM-1001").status_code == 409
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "approve", 420.0)
    assert release(client, "CLM-1001").status_code == 409
    pay(client, "CLM-1001", 420.0)
    assert release(client, "CLM-1001").status_code == 409
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1150.0)
    response = release(client, "CLM-1002")
    assert response.status_code == 409
    assert client.get("/api/claims/CLM-1002").json()["status"] == (
        "waiting_for_sign_off"
    )


def test_release_needs_a_reason(client):
    start(client, "CLM-1005")
    assert release(client, "CLM-1005", "").status_code == 422
    assert release(client, "CLM-9999").status_code == 404
