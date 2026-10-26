"""The UnderCover backend."""

import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from backend import db, seed
from backend.models import (
    AddOn,
    Claim,
    ClaimHistory,
    ClaimState,
    ClaimSummary,
    Customer,
    DecisionRequest,
    Handler,
    PaymentRequest,
    Plan,
    Policy,
    SignOffRequest,
    StartRequest,
    Step,
    StepRequest,
    Text,
)

STATUS_LABELS = {
    "waiting": "waiting",
    "in_progress": "in progress",
    "awaiting_sign_off": "waiting for sign-off",
    "decided": "decided",
}


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


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def money(amount: float) -> str:
    return f"${amount:,.2f}"


def approval_limit(connection: sqlite3.Connection) -> float:
    row = connection.execute(
        "SELECT value FROM settings WHERE key = 'payout_approval_limit'"
    ).fetchone()
    return json.loads(row["value"])


def claim_in(connection: sqlite3.Connection, claim_id: str, status: str) -> None:
    """Raise a 409 unless the claim has the given status."""
    current = fetch_one(connection, "claim", claim_id)["status"]
    if current != status:
        raise HTTPException(409, f"Claim {claim_id} is {STATUS_LABELS[current]}.")


def set_status(connection: sqlite3.Connection, claim_id: str, status: str) -> None:
    connection.execute(
        "UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id)
    )


def outcome(connection: sqlite3.Connection, claim_id: str) -> dict[str, object]:
    """Return a claim's decision, sign-off and payment, each None until made."""
    decision = connection.execute(
        """SELECT decision, payout, reason, policy_section, decided_at
        FROM decisions WHERE claim_id = ?""",
        (claim_id,),
    ).fetchone()
    sign_off = connection.execute(
        """SELECT handler_id, name AS handler_name, signed_off_at
        FROM sign_offs JOIN handlers USING (handler_id) WHERE claim_id = ?""",
        (claim_id,),
    ).fetchone()
    payment = connection.execute(
        "SELECT amount, paid_at FROM payments WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    return {
        "decision": dict(decision) if decision else None,
        "sign_off": dict(sign_off) if sign_off else None,
        "payment": dict(payment) if payment else None,
    }


def claim_state(connection: sqlite3.Connection, claim_id: str) -> ClaimState:
    claim = fetch_one(connection, "claim", claim_id)
    return ClaimState.model_validate(
        {"claim_id": claim_id, "status": claim["status"]}
        | outcome(connection, claim_id)
    )


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
        amount_claimed, submitted_on, status, decision, payout
        FROM claims JOIN customers USING (customer_id)
        LEFT JOIN decisions USING (claim_id)
        ORDER BY claim_id"""
    ).fetchall()
    return [ClaimSummary.model_validate(dict(row)) for row in rows]


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, connection: DB) -> Claim:
    """Get a claim in full, with its decision, sign-off and payment."""
    row = dict(fetch_one(connection, "claim", claim_id))
    return Claim.model_validate(
        row
        | {
            "items": json.loads(row["items"]),
            "documents": json.loads(row["documents"]),
        }
        | outcome(connection, claim_id)
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


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, request: StartRequest, connection: DB) -> ClaimState:
    """Start an agent run on a waiting claim, which puts it in progress."""
    with connection:
        claim_in(connection, claim_id, "waiting")
        set_status(connection, claim_id, "in_progress")
        add_step(
            connection,
            claim_id,
            StepRequest(
                thread_id=request.thread_id,
                kind="note",
                text="The agent started work on the claim.",
            ),
        )
    return claim_state(connection, claim_id)


def add_step(
    connection: sqlite3.Connection, claim_id: str, request: StepRequest
) -> Step:
    created_at = now()
    cursor = connection.execute(
        """INSERT INTO steps (claim_id, thread_id, kind, text, created_at)
        VALUES (?, ?, ?, ?, ?)""",
        (claim_id, request.thread_id, request.kind, request.text, created_at),
    )
    return Step.model_validate(
        request.model_dump() | {"step_id": cursor.lastrowid, "created_at": created_at}
    )


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, connection: DB) -> list[Step]:
    """List the steps agents have taken on a claim, oldest first."""
    fetch_one(connection, "claim", claim_id)
    rows = connection.execute(
        """SELECT step_id, thread_id, kind, text, created_at
        FROM steps WHERE claim_id = ? ORDER BY step_id""",
        (claim_id,),
    ).fetchall()
    return [Step.model_validate(dict(row)) for row in rows]


@app.post("/api/claims/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, request: StepRequest, connection: DB) -> Step:
    """Record one step the agent took on a claim."""
    with connection:
        fetch_one(connection, "claim", claim_id)
        return add_step(connection, claim_id, request)


@app.post("/api/claims/{claim_id}/release", operation_id="release_claim")
def release_claim(claim_id: str, connection: DB) -> ClaimState:
    """Put a claim in progress back in the queue, undecided."""
    with connection:
        claim_in(connection, claim_id, "in_progress")
        set_status(connection, claim_id, "waiting")
    return claim_state(connection, claim_id)


@app.post("/api/claims/{claim_id}/decision", operation_id="decide_claim")
def decide_claim(claim_id: str, request: DecisionRequest, connection: DB) -> ClaimState:
    """Approve, decline or refer a claim in progress, with the payout and reason."""
    with connection:
        claim_in(connection, claim_id, "in_progress")
        connection.execute(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?)",
            (
                claim_id,
                request.decision,
                request.payout,
                request.reason,
                request.policy_section,
                now(),
            ),
        )
        over_limit = request.payout > approval_limit(connection)
        set_status(
            connection, claim_id, "awaiting_sign_off" if over_limit else "decided"
        )
    return claim_state(connection, claim_id)


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, request: PaymentRequest, connection: DB) -> ClaimState:
    """Pay an approved claim its approved payout."""
    with connection:
        state = claim_state(connection, claim_id)
        decision = state.decision
        if decision is None or decision.decision != "approve":
            raise HTTPException(409, f"Claim {claim_id} has not been approved.")
        if state.payment:
            raise HTTPException(409, f"Claim {claim_id} has already been paid.")
        if round(request.amount, 2) != decision.payout:
            raise HTTPException(
                409, f"The approved payout is {money(decision.payout)}."
            )
        limit = approval_limit(connection)
        if decision.payout > limit and state.sign_off is None:
            raise HTTPException(
                403, f"A payout over {money(limit)} needs a handler's sign-off."
            )
        connection.execute(
            "INSERT INTO payments VALUES (?, ?, ?)", (claim_id, decision.payout, now())
        )
    return claim_state(connection, claim_id)


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(
    claim_id: str, request: SignOffRequest, connection: DB
) -> ClaimState:
    """Sign off a payout over the limit as a handler, which pays it."""
    with connection:
        claim_in(connection, claim_id, "awaiting_sign_off")
        handler = connection.execute(
            "SELECT * FROM handlers WHERE handler_id = ?", (request.handler_id,)
        ).fetchone()
        if handler is None:
            raise HTTPException(404, f"There is no handler {request.handler_id}.")
        if not handler["can_approve_over_limit"]:
            raise HTTPException(
                403, f"{handler['name']} can't sign off payouts over the limit."
            )
        connection.execute(
            "INSERT INTO sign_offs VALUES (?, ?, ?)",
            (claim_id, request.handler_id, now()),
        )
        connection.execute(
            """INSERT INTO payments
            SELECT claim_id, payout, ? FROM decisions WHERE claim_id = ?""",
            (now(), claim_id),
        )
        set_status(connection, claim_id, "decided")
    return claim_state(connection, claim_id)
