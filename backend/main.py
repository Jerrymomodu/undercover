"""The UnderCover backend."""

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from backend import db, seed
from backend.models import (
    AddOn,
    Claim,
    ClaimHistory,
    ClaimSummary,
    Customer,
    Handler,
    Plan,
    Policy,
    Text,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if not db.path().exists():
        seed.seed()
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)

DB = Annotated[sqlite3.Connection, Depends(db.get_db)]


def fetch_one(connection: sqlite3.Connection, table: str, key: str) -> sqlite3.Row:
    """Return the row whose id is key, or raise a 404."""
    queries = {
        "claim": "SELECT * FROM claims WHERE claim_id = ?",
        "policy": "SELECT * FROM policies WHERE policy_id = ?",
        "customer": "SELECT * FROM customers WHERE customer_id = ?",
    }
    row = connection.execute(queries[table], (key,)).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no {table} {key}.")
    return row


def document(connection: sqlite3.Connection, name: str) -> Text:
    row = connection.execute(
        "SELECT content FROM documents WHERE name = ?", (name,)
    ).fetchone()
    return Text(content=row["content"])


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(connection: DB) -> list[ClaimSummary]:
    """List every claim in the queue with where it stands."""
    rows = connection.execute(
        """SELECT claim_id, customers.name AS customer_name, claim_type,
        amount_claimed, submitted_on, status
        FROM claims JOIN customers USING (customer_id)
        ORDER BY claim_id"""
    ).fetchall()
    return [ClaimSummary.model_validate(dict(row)) for row in rows]


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, connection: DB) -> Claim:
    """Get a claim in full: the story, the items and the documents."""
    row = dict(fetch_one(connection, "claim", claim_id))
    return Claim.model_validate(
        row
        | {
            "items": json.loads(row["items"]),
            "documents": json.loads(row["documents"]),
        }
    )


@app.get("/api/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, connection: DB) -> Policy:
    """Get a policy with its plan's limits and the add-ons bought."""
    row = dict(fetch_one(connection, "policy", policy_id))
    plan = connection.execute(
        "SELECT * FROM plans WHERE plan = ?", (row["plan"],)
    ).fetchone()
    add_ons = [
        connection.execute("SELECT * FROM add_ons WHERE add_on = ?", (a,)).fetchone()
        for a in json.loads(row["add_ons"])
    ]
    return Policy.model_validate(
        row
        | {
            "plan": Plan.model_validate(dict(plan)),
            "add_ons": [AddOn.model_validate(dict(a)) for a in add_ons],
            "trip": json.loads(row["trip"]),
            "travelers": json.loads(row["travelers"]),
        }
    )


@app.get("/api/customers/{customer_id}", operation_id="get_customer")
def get_customer(customer_id: str, connection: DB) -> Customer:
    """Get a customer's contact details and claim history."""
    row = dict(fetch_one(connection, "customer", customer_id))
    return Customer.model_validate(
        row
        | {
            "address": json.loads(row["address"]),
            "previous_claims": json.loads(row["previous_claims"]),
        }
    )


@app.get("/api/customers/{customer_id}/claim-history", operation_id="get_claim_history")
def get_claim_history(customer_id: str, connection: DB) -> ClaimHistory:
    """Get a customer's earlier claims, without their contact details."""
    row = fetch_one(connection, "customer", customer_id)
    return ClaimHistory(
        customer_id=customer_id,
        previous_claims=json.loads(row["previous_claims"]),
    )


@app.get("/api/policy-wording", operation_id="get_policy_wording")
def get_policy_wording(connection: DB) -> Text:
    """Get the policy wording that decisions follow."""
    return document(connection, "policy_wording")


@app.get("/api/instructions", operation_id="get_instructions")
def get_instructions(connection: DB) -> Text:
    """Get the UnderCover Agent's instructions."""
    return document(connection, "instructions")


@app.get("/api/handlers", operation_id="list_handlers")
def list_handlers(connection: DB) -> list[Handler]:
    """List the claims handlers."""
    rows = connection.execute("SELECT * FROM handlers ORDER BY handler_id").fetchall()
    return [Handler.model_validate(dict(row)) for row in rows]
