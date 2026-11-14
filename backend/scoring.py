"""Scoring an evaluation against the handlers' decisions, from the backend's records.

The only module that reads the answer key. It follows our team's labs: a claim the
agent didn't decide counts as a referral.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Column, Connection, Subquery, func, select

from backend.database import (
    answer_key,
    claims,
    decisions,
    model_calls,
    run_claims,
    work_times,
)
from backend.models import DecisionKind, Measures, Run, ScoredClaim

WRONGFUL_DECLINE = 1500
NEEDLESS_REFERRAL = 50
PAYOUT_LEEWAY = 1
UNDECIDED: DecisionKind = "refer"


def mistake_cost(
    agent: DecisionKind, agent_payout: float, handler: DecisionKind, payout: float
) -> float:
    """What the agent's answer costs UnderCover, against the handler's decision."""
    if agent == handler:
        return abs(agent_payout - payout) if agent == "approve" else 0
    if agent == "decline":
        return WRONGFUL_DECLINE
    if agent == "approve":
        return agent_payout
    return NEEDLESS_REFERRAL


def labelled_claims(db: Connection, eval_set: str, tiny: bool) -> set[str]:
    """The ids of the claims a labelled set has the handlers' decisions for, whole
    or just its five tiny claims."""
    query = select(answer_key.c.claim_id).where(answer_key.c.eval_set == eval_set)
    if tiny:
        query = query.where(answer_key.c.tiny)
    return set(db.execute(query).scalars())


def per_claim(column: Column[float], name: str) -> Subquery:
    """Sum one column of a table for each claim, as a subquery."""
    table = column.table
    return (
        select(table.c.claim_id, func.sum(column).label(name))
        .group_by(table.c.claim_id)
        .subquery()
    )


def scored_claims(db: Connection, run: Run) -> list[ScoredClaim]:
    """Each of an evaluation's copies, with the handler's decision beside the
    agent's, whether the agent was right, and what the claim cost and took."""
    costs = per_claim(model_calls.c.cost, "cost")
    times = per_claim(work_times.c.seconds, "seconds")
    query = (
        select(
            claims.c.claim_id,
            claims.c.copy_of,
            answer_key.c.decision.label("handler_decision"),
            answer_key.c.payout.label("handler_payout"),
            decisions.c.decision,
            decisions.c.payout,
            decisions.c.reason,
            func.coalesce(costs.c.cost, 0.0).label("cost"),
            func.coalesce(times.c.seconds, 0.0).label("seconds"),
        )
        .join(run_claims, run_claims.c.claim_id == claims.c.claim_id)
        .join(
            answer_key,
            (answer_key.c.claim_id == claims.c.copy_of)
            & (answer_key.c.eval_set == run.eval_set),
        )
        .outerjoin(decisions, decisions.c.claim_id == claims.c.claim_id)
        .outerjoin(costs, costs.c.claim_id == claims.c.claim_id)
        .outerjoin(times, times.c.claim_id == claims.c.claim_id)
        .where(run_claims.c.run_id == run.run_id)
        .order_by(run_claims.c.position)
    )
    return [score(row) for row in db.execute(query).mappings()]


def score(row: Mapping[Any, Any]) -> ScoredClaim:
    """Score one claim, counting no decision as a referral with nothing paid."""
    agent = row["decision"] or UNDECIDED
    agent_payout = row["payout"] or 0.0
    handler, payout = row["handler_decision"], row["handler_payout"]
    return ScoredClaim(
        claim_id=row["claim_id"],
        copy_of=row["copy_of"],
        handler_decision=handler,
        handler_payout=payout,
        decision=row["decision"],
        payout=row["payout"],
        reason=row["reason"],
        agent_decision=agent,
        right=agent == handler and abs(agent_payout - payout) <= PAYOUT_LEEWAY,
        mistake_cost=mistake_cost(agent, agent_payout, handler, payout),
        cost=row["cost"],
        seconds=row["seconds"],
    )


def measures(run: Run, scored: list[ScoredClaim]) -> Measures:
    """The scoreboard's measures for one evaluation: quality, cost and time."""
    count = len(scored)
    run_seconds = None
    if run.finished_at:
        took = datetime.fromisoformat(run.finished_at) - datetime.fromisoformat(
            run.started_at
        )
        run_seconds = took.total_seconds()
    return Measures(
        decision_accuracy=sum(c.agent_decision == c.handler_decision for c in scored)
        / count,
        accuracy=sum(claim.right for claim in scored) / count,
        cost_of_mistakes=sum(claim.mistake_cost for claim in scored),
        straight_through=sum(c.agent_decision != UNDECIDED for c in scored) / count,
        cost_per_claim=run.cost / count,
        seconds_per_claim=sum(claim.seconds for claim in scored) / count,
        run_seconds=run_seconds,
    )
