"""The UnderCover backend."""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import (
    Column,
    Connection,
    RowMapping,
    delete,
    func,
    insert,
    select,
    update,
)

from backend import agent_service, scoring
from backend.database import (
    claim_view,
    claims,
    customers,
    decisions,
    engine,
    handlers,
    held_out_claims,
    is_seeded,
    model_calls,
    payments,
    policies,
    run_claims,
    runs,
    seed,
    settings,
    steps,
    work_times,
)
from backend.documents import contents, search, sections, titles
from backend.models import (
    ACCEPTED,
    DISPATCH,
    EVALUATION,
    EVALUATION_SET,
    FINISHED,
    RUNNING,
    STOPPED,
    Claim,
    ClaimSummary,
    Decision,
    DecisionKind,
    DecisionRequest,
    DispatchRequest,
    DocumentName,
    Evaluation,
    EvaluationDetail,
    EvaluationRequest,
    FailureRequest,
    Handler,
    HeldPayout,
    Instructions,
    ModelCall,
    ModelCallRequest,
    Payment,
    PaymentRequest,
    Payout,
    PayoutRequest,
    Plans,
    Policy,
    PreviousClaim,
    Run,
    RunClaim,
    RunClaimsRequest,
    RunSummary,
    Section,
    SectionMatch,
    SignOffRequest,
    StartDispatchRequest,
    StartEvaluationRequest,
    StartRequest,
    Status,
    Step,
    StepRequest,
    WorkTime,
    WorkTimeRequest,
)
from backend.payout import needs_sign_off, work_out_payout

INSTRUCTIONS = Path(__file__).parent / "instructions"
ATTEMPTS = 2


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed the database on startup if it has no tables yet."""
    if not is_seeded(engine()):
        seed(engine())
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)


@app.exception_handler(agent_service.Refused)
def agent_refused(_: Request, error: agent_service.Refused) -> JSONResponse:
    """Pass on why the agent's service didn't start a run."""
    return JSONResponse({"detail": error.detail}, status_code=error.status_code)


def database() -> Iterator[Connection]:
    """Open the database for one request, in a transaction committed at its end."""
    with engine().begin() as connection:
        yield connection


# Committed before the response is sent and before any background task runs.
Database = Annotated[Connection, Depends(database, scope="function")]


def now() -> str:
    """Return the current time in UTC, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def dollars(amount: float) -> str:
    """Format an amount like $1,250.00."""
    return f"${amount:,.2f}"


def approval_limit(db: Connection) -> float:
    """Return the largest payout that can be paid without a handler's sign-off."""
    return db.execute(select(settings.c.payout_approval_limit)).scalar_one()


def plans(db: Connection) -> Plans:
    """Return the plans and add-ons, and the benefits the deductible applies to."""
    return Plans(**db.execute(select(settings.c.plans)).scalar_one())


def find_claim(db: Connection, claim_id: str) -> RowMapping:
    """Return one claim's row, or raise a 404."""
    query = claim_view.where(claims.c.claim_id == claim_id)
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"Claim {claim_id} not found")
    return row


def find_policy(db: Connection, policy_id: str) -> Policy:
    """Return one policy, or raise a 404."""
    query = select(policies.c.record).where(policies.c.policy_id == policy_id)
    record = db.execute(query).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return Policy(**record)


def set_status(db: Connection, claim_id: str, status: Status) -> None:
    """Move a claim to a new status."""
    db.execute(
        update(claims).where(claims.c.claim_id == claim_id).values(status=status)
    )


def to_summary(row: RowMapping) -> ClaimSummary:
    """Build a claim's line in the queue from its row."""
    return ClaimSummary(
        **row["record"]
        | {
            "status": row["status"],
            "customer_name": row["customer_name"],
            "decision": row["decision"],
            "payout": row["payout"],
        }
    )


def to_claim(row: RowMapping) -> Claim:
    """Build a claim in full, with its decision and payment, from its row."""
    decision = None
    if row["decision"] is not None:
        decision = Decision(**{field: row[field] for field in Decision.model_fields})
    payment = None
    if row["paid_at"] is not None:
        payment = Payment(**{field: row[field] for field in Payment.model_fields})
    return Claim(
        **row["record"]
        | {
            "status": row["status"],
            "customer_name": row["customer_name"],
            "thread_id": row["thread_id"],
            "attempts": row["attempts"],
            "evaluation_id": row["evaluation_id"],
            "copy_of": row["copy_of"],
            "decision": decision,
            "payment": payment,
        }
    )


def add_step(
    db: Connection, claim_id: str, thread_id: str, kind: str, content: str
) -> Step:
    """Add one step of the agent's work to a claim."""
    query = (
        insert(steps)
        .values(
            claim_id=claim_id,
            thread_id=thread_id,
            kind=kind,
            content=content,
            created_at=now(),
        )
        .returning(steps)
    )
    return Step(**db.execute(query).mappings().one())


def find_run_row(db: Connection, run_id: str) -> RowMapping:
    """Return one run's row, or raise a 404."""
    row = db.execute(select(runs).where(runs.c.run_id == run_id)).mappings().first()
    if row is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return row


def summarize(items: list[RunClaim]) -> RunSummary:
    """Sum up how a run's claims stand, from the records alone."""

    def with_status(status: Status) -> list[RunClaim]:
        return [claim for claim in items if claim.status == status]

    def decided(decision: DecisionKind) -> int:
        return sum(claim.decision == decision for claim in items)

    return RunSummary(
        approved=decided("approve"),
        declined=decided("decline"),
        referred=decided("refer"),
        waiting_for_sign_off=[
            HeldPayout(claim_id=claim.claim_id, payout=claim.payout or 0)
            for claim in with_status("waiting_for_sign_off")
        ],
        left_for_handler=[c.claim_id for c in with_status("left_for_handler")],
        in_progress=[c.claim_id for c in with_status("in_progress")],
        waiting=[c.claim_id for c in with_status("waiting")],
    )


def run_total(db: Connection, column: Column[float], run_id: str) -> float:
    """Add up one column of a run's model calls or work times."""
    query = select(func.coalesce(func.sum(column), 0.0)).where(
        column.table.c.run_id == run_id
    )
    return db.execute(query).scalar_one()


def find_run(db: Connection, run_id: str) -> Run:
    """Return one run with its claims and where each stands, its summary, and what
    its model calls cost and its claims took, or raise a 404."""
    row = find_run_row(db, run_id)
    query = (
        claim_view.join(run_claims, run_claims.c.claim_id == claims.c.claim_id)
        .where(run_claims.c.run_id == run_id)
        .order_by(run_claims.c.position)
    )
    items = [
        RunClaim(**{field: claim[field] for field in RunClaim.model_fields})
        for claim in db.execute(query).mappings()
    ]
    return Run(
        **row,
        claims=items,
        summary=summarize(items),
        cost=run_total(db, model_calls.c.cost, run_id),
        agent_seconds=run_total(db, work_times.c.seconds, run_id),
    )


def running_run(db: Connection, run_id: str) -> Run:
    """Return a run that is still running, or raise a 404 or a 409."""
    run = find_run(db, run_id)
    if run.status != RUNNING:
        raise HTTPException(409, f"Run {run_id} is not running")
    return run


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(db: Database) -> list[ClaimSummary]:
    """List every claim in the queue, in id order, leaving out evaluations' copies."""
    query = claim_view.where(claims.c.evaluation_id.is_(None))
    rows = db.execute(query.order_by(claims.c.claim_id)).mappings()
    return [to_summary(row) for row in rows]


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, db: Database) -> Claim:
    """Get one claim in full: the story, the items claimed and the documents."""
    return to_claim(find_claim(db, claim_id))


@app.get("/api/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, db: Database) -> Policy:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    return find_policy(db, policy_id)


@app.get("/api/customers/{customer_id}/claims", operation_id="get_claim_history")
def get_claim_history(customer_id: str, db: Database) -> list[PreviousClaim]:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    query = select(customers.c.record).where(customers.c.customer_id == customer_id)
    record = db.execute(query).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, f"Customer {customer_id} not found")
    return [PreviousClaim(**claim) for claim in record["previous_claims"]]


@app.get("/api/instructions", operation_id="get_instructions")
def get_instructions(db: Database) -> Instructions:
    """Get the claim agent's instructions, with the contents of the documents."""
    claim = (INSTRUCTIONS / "claim.md").read_text(encoding="utf-8")
    return Instructions(claim=f"{claim}\n{contents(db)}")


@app.get("/api/documents/search", operation_id="search_documents")
def search_documents(
    query: Annotated[str, Query(min_length=1)], db: Database
) -> list[SectionMatch]:
    """Find the sections of the wording and the manual that mention a word or phrase."""
    return search(db, query)


@app.get("/api/documents/{document}/sections/{number}", operation_id="read_section")
def read_section(document: DocumentName, number: int, db: Database) -> Section:
    """Read one section of the policy wording or the claims manual in full."""
    for section in sections(db, document):
        if section.number == number:
            return section
    title = titles(db)[document].lower()
    raise HTTPException(404, f"Section {number} of the {title} not found")


@app.get("/api/handlers", operation_id="list_handlers")
def list_handlers(db: Database) -> list[Handler]:
    """List the claims handlers."""
    rows = db.execute(select(handlers).order_by(handlers.c.handler_id)).mappings()
    return [Handler(**row) for row in rows]


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, request: StartRequest, db: Database) -> Claim:
    """Start work on a waiting claim, which moves it to in progress."""
    if find_claim(db, claim_id)["status"] != "waiting":
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    db.execute(
        update(claims)
        .where(claims.c.claim_id == claim_id)
        .values(
            status="in_progress",
            thread_id=request.thread_id,
            attempts=claims.c.attempts + 1,
        )
    )
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, request: StepRequest, db: Database) -> Step:
    """Record one step of the agent's work on a claim."""
    thread_id = find_claim(db, claim_id)["thread_id"]
    if thread_id is None:
        raise HTTPException(409, f"Claim {claim_id} has not been started")
    return add_step(db, claim_id, thread_id, request.kind, request.content)


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, db: Database) -> list[Step]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(db, claim_id)
    query = select(steps).where(steps.c.claim_id == claim_id).order_by(steps.c.step_id)
    return [Step(**row) for row in db.execute(query).mappings()]


@app.post("/api/claims/{claim_id}/model-calls", operation_id="record_model_call")
def record_model_call(
    claim_id: str, request: ModelCallRequest, db: Database
) -> ModelCall:
    """Record the tokens and cost of one of the agent's model calls on a claim."""
    find_claim(db, claim_id)
    if request.run_id is not None:
        find_run_row(db, request.run_id)
    query = (
        insert(model_calls)
        .values(claim_id=claim_id, created_at=now(), **request.model_dump())
        .returning(model_calls)
    )
    return ModelCall(**db.execute(query).mappings().one())


@app.post("/api/claims/{claim_id}/work-times", operation_id="record_work_time")
def record_work_time(claim_id: str, request: WorkTimeRequest, db: Database) -> WorkTime:
    """Record how long the agent has just worked on a claim in one go."""
    find_claim(db, claim_id)
    if request.run_id is not None:
        find_run_row(db, request.run_id)
    started = datetime.now(UTC) - timedelta(seconds=request.seconds)
    query = (
        insert(work_times)
        .values(
            claim_id=claim_id,
            run_id=request.run_id,
            started_at=started.isoformat(timespec="seconds"),
            seconds=request.seconds,
        )
        .returning(work_times)
    )
    return WorkTime(**db.execute(query).mappings().one())


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, request: DecisionRequest, db: Database) -> Claim:
    """Record a claim's decision once; an approval waits to be paid or signed off."""
    claim = find_claim(db, claim_id)
    payout = round(request.payout, 2)
    if claim["decision"] is not None:
        if (claim["decision"], claim["payout"]) == (request.decision, payout):
            return to_claim(claim)
        raise HTTPException(409, f"Claim {claim_id} has already been decided")
    if claim["status"] != "in_progress":
        raise HTTPException(409, f"Claim {claim_id} is not in progress")
    db.execute(
        insert(decisions).values(
            claim_id=claim_id,
            decision=request.decision,
            payout=payout,
            section=request.section,
            reason=request.reason,
            decided_at=now(),
        )
    )
    if request.decision != "approve":
        set_status(db, claim_id, "decided")
    elif needs_sign_off(payout, approval_limit(db)):
        set_status(db, claim_id, "waiting_for_sign_off")
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/payout", operation_id="calculate_payout")
def calculate_payout(claim_id: str, request: PayoutRequest, db: Database) -> Payout:
    """Work out an approval's payout with UnderCover's payout rules; records nothing."""
    policy = find_policy(db, to_claim(find_claim(db, claim_id)).policy_id)
    return work_out_payout(policy, plans(db), request, approval_limit(db))


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, request: PaymentRequest, db: Database) -> Claim:
    """Pay an approved claim its payout once, unless it needs a handler's sign-off."""
    claim = find_claim(db, claim_id)
    if claim["decision"] != "approve":
        raise HTTPException(409, f"Claim {claim_id} has not been approved")
    amount = round(request.amount, 2)
    if claim["paid_at"] is not None:
        if amount == claim["amount"]:
            return to_claim(claim)
        raise HTTPException(409, f"Claim {claim_id} has already been paid")
    if claim["status"] == "waiting_for_sign_off":
        raise HTTPException(
            403,
            f"A payout over {dollars(approval_limit(db))} needs a handler's sign-off",
        )
    if amount != claim["payout"]:
        raise HTTPException(
            422, f"The amount must be the approved payout of {dollars(claim['payout'])}"
        )
    db.execute(
        insert(payments).values(
            claim_id=claim_id, amount=claim["payout"], paid_at=now()
        )
    )
    set_status(db, claim_id, "decided")
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(
    claim_id: str, request: SignOffRequest, db: Database, background: BackgroundTasks
) -> Claim:
    """Sign off a held payout as a handler, so the agent picks the claim up and pays."""
    claim = find_claim(db, claim_id)
    if claim["evaluation_id"] is not None:
        raise HTTPException(409, f"Claim {claim_id} is an evaluation's copy")
    if claim["status"] != "waiting_for_sign_off":
        raise HTTPException(409, f"Claim {claim_id} is not waiting for sign-off")
    query = select(handlers).where(handlers.c.handler_id == request.handler_id)
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, f"Handler {request.handler_id} not found")
    handler = Handler(**row)
    if not handler.can_approve_over_limit:
        raise HTTPException(
            403,
            f"{handler.name} can't sign off payouts over {dollars(approval_limit(db))}",
        )
    db.execute(
        update(decisions)
        .where(decisions.c.claim_id == claim_id)
        .values(signed_off_by=handler.name, signed_off_at=now())
    )
    set_status(db, claim_id, "in_progress")
    background.add_task(agent_service.resume_claim, claim_id)
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/failure", operation_id="fail_claim")
def fail_claim(claim_id: str, request: FailureRequest, db: Database) -> Claim:
    """Put a failed claim back in the queue, or leave it for a handler after two."""
    claim = find_claim(db, claim_id)
    if claim["status"] != "in_progress":
        raise HTTPException(409, f"Claim {claim_id} is not in progress")
    if claim["decision"] is not None:
        raise HTTPException(409, f"Claim {claim_id} has already been decided")
    add_step(db, claim_id, claim["thread_id"], "error", request.reason)
    status = "left_for_handler" if claim["attempts"] >= ATTEMPTS else "waiting"
    set_status(db, claim_id, status)
    return to_claim(find_claim(db, claim_id))


@app.post("/api/dispatches/start", operation_id="start_dispatch", status_code=202)
def start_dispatch(request: StartDispatchRequest) -> dict[str, str]:
    """Ask the agent's service to start a dispatch with up to N claim agents at once."""
    agent_service.start_dispatch(request.agents)
    return ACCEPTED


@app.get("/api/dispatches/latest", operation_id="get_latest_dispatch")
def get_latest_dispatch(db: Database) -> Run | None:
    """Get the newest dispatch with its claims, summary, cost and time, or nothing."""
    query = (
        select(runs.c.run_id)
        .where(runs.c.kind == DISPATCH)
        .order_by(runs.c.number.desc())
        .limit(1)
    )
    run_id = db.execute(query).scalar_one_or_none()
    return None if run_id is None else find_run(db, run_id)


@app.post("/api/evaluations/start", operation_id="start_evaluation", status_code=202)
def start_evaluation(request: StartEvaluationRequest) -> dict[str, str]:
    """Ask the agent's service to start an evaluation on copies of a labelled set."""
    agent_service.start_evaluation(request.agents, request.eval_set, request.tiny)
    return ACCEPTED


@app.get("/api/evaluations", operation_id="list_evaluations")
def list_evaluations(db: Database) -> list[Evaluation]:
    """List the evaluations, newest first, with their measures."""
    query = (
        select(runs.c.run_id)
        .where(runs.c.kind == EVALUATION)
        .order_by(runs.c.number.desc())
    )
    found = [find_run(db, run_id) for run_id in db.execute(query).scalars()]
    return [
        Evaluation(
            run=run, measures=scoring.measures(run, scoring.scored_claims(db, run))
        )
        for run in found
    ]


@app.get("/api/evaluations/{run_id}", operation_id="get_evaluation")
def get_evaluation(run_id: str, db: Database) -> EvaluationDetail:
    """Get one evaluation's measures, and its claims beside the handlers' decisions."""
    run = find_run(db, run_id)
    if run.kind != EVALUATION:
        raise HTTPException(404, f"Evaluation {run_id} not found")
    scored = scoring.scored_claims(db, run)
    return EvaluationDetail(
        run=run, measures=scoring.measures(run, scored), claims=scored
    )


def originals(db: Connection, request: EvaluationRequest) -> list[dict[str, Any]]:
    """The records of the labelled claims to copy, whole set or just the tiny ones:
    the queue's own claims for the evaluation set, or the held-out claims."""
    table = claims if request.eval_set == EVALUATION_SET else held_out_claims
    labelled = scoring.labelled_claims(db, request.eval_set, request.tiny)
    query = (
        select(table.c.record)
        .where(table.c.claim_id.in_(labelled))
        .order_by(table.c.claim_id)
    )
    return list(db.execute(query).scalars())


def copy_claims(
    db: Connection, run_id: str, number: int, records: list[dict[str, Any]]
) -> None:
    """Copy the claims for an evaluation, out of the queue, each with a new id written
    into its record too, and link them to the evaluation."""
    copies = [
        (record | {"claim_id": f"E{number}-{record['claim_id']}"}, record["claim_id"])
        for record in records
    ]
    db.execute(
        insert(claims),
        [
            {
                "claim_id": copy["claim_id"],
                "customer_id": copy["customer_id"],
                "record": copy,
                "status": "waiting",
                "thread_id": None,
                "attempts": 0,
                "evaluation_id": run_id,
                "copy_of": original,
            }
            for copy, original in copies
        ],
    )
    db.execute(
        insert(run_claims),
        [
            {"run_id": run_id, "position": position, "claim_id": copy["claim_id"]}
            for position, (copy, _) in enumerate(copies)
        ],
    )


@app.post("/api/evaluations", operation_id="create_evaluation")
def create_evaluation(request: EvaluationRequest, db: Database) -> Run:
    """Record a new evaluation and make its copies of the labelled claims."""
    run_id = str(uuid.uuid4())
    number = db.execute(
        insert(runs)
        .values(
            run_id=run_id,
            kind=EVALUATION,
            status=RUNNING,
            started_at=now(),
            **request.model_dump(),
        )
        .returning(runs.c.number)
    ).scalar_one()
    copy_claims(db, run_id, number, originals(db, request))
    return find_run(db, run_id)


@app.post("/api/dispatches", operation_id="create_dispatch")
def create_dispatch(request: DispatchRequest, db: Database) -> Run:
    """Record a new dispatch, with N, the model and its reasoning effort."""
    run_id = str(uuid.uuid4())
    db.execute(
        insert(runs).values(
            run_id=run_id,
            kind=DISPATCH,
            status=RUNNING,
            started_at=now(),
            **request.model_dump(),
        )
    )
    return find_run(db, run_id)


@app.put("/api/runs/{run_id}/claims", operation_id="add_run_claims")
def add_run_claims(run_id: str, request: RunClaimsRequest, db: Database) -> Run:
    """Record the claims a running dispatch works, in the order it listed them."""
    if running_run(db, run_id).kind != DISPATCH:
        raise HTTPException(409, f"Run {run_id} is not a dispatch")
    for claim_id in request.claim_ids:
        if find_claim(db, claim_id)["evaluation_id"] is not None:
            raise HTTPException(409, f"Claim {claim_id} is an evaluation's copy")
    db.execute(delete(run_claims).where(run_claims.c.run_id == run_id))
    if request.claim_ids:
        db.execute(
            insert(run_claims),
            [
                {"run_id": run_id, "position": position, "claim_id": claim_id}
                for position, claim_id in enumerate(request.claim_ids)
            ],
        )
    return find_run(db, run_id)


@app.get("/api/runs/{run_id}", operation_id="get_run")
def get_run(run_id: str, db: Database) -> Run:
    """Get a dispatch or an evaluation with its claims and where each stands."""
    return find_run(db, run_id)


@app.post("/api/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: str, db: Database) -> Run:
    """Finish a running dispatch or evaluation, once its claim agents have finished."""
    running_run(db, run_id)
    db.execute(
        update(runs)
        .where(runs.c.run_id == run_id)
        .values(status=FINISHED, finished_at=now())
    )
    return find_run(db, run_id)


@app.post("/api/runs/stop", operation_id="stop_runs")
def stop_runs(db: Database) -> list[Run]:
    """Mark every run still running as stopped, as the agent's service starts."""
    query = (
        update(runs)
        .where(runs.c.status == RUNNING)
        .values(status=STOPPED)
        .returning(runs.c.run_id)
    )
    stopped = list(db.execute(query).scalars())
    return [find_run(db, run_id) for run_id in stopped]
