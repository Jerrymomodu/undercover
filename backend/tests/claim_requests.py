"""Requests the backend's tests send to work a claim."""


def start(client, claim_id):
    return client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "t-1"})


def decide(client, claim_id, decision, payout):
    return client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": decision,
            "payout": payout,
            "section": "Section 3, Trip Delay",
            "reason": "The delay was covered.",
        },
    )


def pay(client, claim_id, amount):
    return client.post(f"/api/claims/{claim_id}/payment", json={"amount": amount})


def sign_off(client, claim_id, handler_id):
    return client.post(
        f"/api/claims/{claim_id}/sign-off", json={"handler_id": handler_id}
    )


def fail(client, claim_id, reason="The model timed out"):
    return client.post(f"/api/claims/{claim_id}/failure", json={"reason": reason})


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
