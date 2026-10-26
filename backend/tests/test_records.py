import json
from contextlib import closing

from fastapi.testclient import TestClient

from backend import db, seed
from backend.main import INSTRUCTIONS, app


def counts() -> dict[str, int]:
    with closing(db.connect()) as connection:
        row = connection.execute(
            """SELECT (SELECT COUNT(*) FROM claims) AS claims,
            (SELECT COUNT(*) FROM policies) AS policies,
            (SELECT COUNT(*) FROM customers) AS customers,
            (SELECT COUNT(*) FROM plans) AS plans,
            (SELECT COUNT(*) FROM add_ons) AS add_ons,
            (SELECT COUNT(*) FROM handlers) AS handlers,
            (SELECT COUNT(*) FROM decisions) AS decisions"""
        ).fetchone()
    return dict(row)


def test_seed_loads_the_business_data(client):
    assert counts() == {
        "claims": 25,
        "policies": 50,
        "customers": 49,
        "plans": 3,
        "add_ons": 3,
        "handlers": 3,
        "decisions": 0,
    }
    statuses = {c["status"] for c in client.get("/api/claims").json()}
    assert statuses == {"waiting"}


def test_seed_holds_only_the_queue(client):
    queue = json.loads((seed.DATA / "claims.json").read_text(encoding="utf-8"))
    ids = [c["claim_id"] for c in client.get("/api/claims").json()]
    assert ids == sorted(c["claim_id"] for c in queue)
    assert "CLM-1901" not in ids
    with closing(db.connect()) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert tables - {"sqlite_sequence"} == {
        "settings",
        "documents",
        "plans",
        "add_ons",
        "handlers",
        "customers",
        "policies",
        "claims",
        "decisions",
        "sign_offs",
        "payments",
        "steps",
    }


def test_seed_runs_again_from_scratch(client):
    seed.seed()
    assert counts()["claims"] == 25


def test_startup_seeds_a_missing_database(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "new.db"))
    with TestClient(app) as client:
        assert len(client.get("/api/claims").json()) == 25


def test_list_claims(client):
    claims = client.get("/api/claims").json()
    assert claims[0] == {
        "claim_id": "CLM-1001",
        "customer_name": "Maya Patel",
        "claim_type": "trip_delay",
        "amount_claimed": 420.0,
        "submitted_on": "2026-06-24",
        "status": "waiting",
        "decision": None,
        "payout": None,
    }


def test_get_claim(client):
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["story"].startswith("My flight home from Rome")
    assert len(claim["items"]) == 3
    assert len(claim["documents"]) == 4
    assert claim["status"] == "waiting"


def test_get_policy(client):
    policy = client.get("/api/policies/POL-2001").json()
    assert policy["plan"]["name"] == "UnderCover Premium"
    assert policy["plan"]["deductible"] == 50.0
    assert policy["plan"]["per_item_limit"] == 300.0
    assert policy["add_ons"] == []
    assert policy["travelers"] == ["Maya Patel"]


def test_get_policy_with_an_add_on(client):
    policy = client.get("/api/policies/POL-2009").json()
    assert policy["add_ons"][0]["add_on"] == "electronics_plus"
    assert policy["add_ons"][0]["electronics_per_item_limit"] == 1200.0


def test_get_customer(client):
    customer = client.get("/api/customers/CUS-3001").json()
    assert customer["name"] == "Maya Patel"
    assert customer["address"]["city"] == "Jersey City"


def test_get_claim_history(client):
    history = client.get("/api/customers/CUS-3001/claim-history").json()
    assert history["customer_id"] == "CUS-3001"
    assert [c["claim_id"] for c in history["previous_claims"]] == ["CLM-0412"]
    assert set(history) == {"customer_id", "previous_claims"}


def test_get_policy_wording(client):
    wording = client.get("/api/policy-wording").json()["content"]
    assert wording.startswith("# UnderCover Travel Insurance: Policy Wording")
    assert "Version 2026.1" in wording


def test_get_instructions(client):
    instructions = client.get("/api/instructions").json()["content"]
    assert instructions == INSTRUCTIONS.read_text(encoding="utf-8")
    assert instructions.startswith("# The UnderCover Agent")


def test_list_handlers(client):
    handlers = client.get("/api/handlers").json()
    assert [h["name"] for h in handlers] == [
        "Dana Whitfield",
        "Marcus Oyelaran",
        "Priya Raman",
    ]
    assert all(h["can_approve_over_limit"] for h in handlers)


def test_unknown_ids_are_not_found(client):
    assert client.get("/api/claims/CLM-9999").status_code == 404
    assert client.get("/api/policies/POL-9999").status_code == 404
    assert client.get("/api/customers/CUS-9999").status_code == 404
    response = client.get("/api/customers/CUS-9999/claim-history")
    assert response.status_code == 404
    assert response.json() == {"detail": "There is no customer CUS-9999."}
