"""One invoice's journey, as stages that save a checkpoint as they go.

checks -> route -> (judge -> guard) -> decide -> (pay) -> done

Each stage works out its result first, which may mean calling the model, then saves the
result and the next stage in one transaction. A worker that dies mid-invoice leaves the
job at its last saved stage, so the next worker resumes there: the model is never asked
twice and the payment is never made twice.
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from invoice_desk.db import decide, load_case, log, pay, transaction
from invoice_desk.judge import Judge
from invoice_desk.models import Case, Finding, Outcome, Verdict
from invoice_desk.rules import enforce, run_checks, triage

Saved = dict[str, Any]


class LeaseLostError(Exception):
    """Another worker now holds this invoice's job."""


@dataclass
class Step:
    """What a stage produced: the checkpoint to save, the next stage, and the event."""

    next_stage: str
    actor: str
    message: str
    saved: Saved = field(default_factory=dict)
    write: Callable[[sqlite3.Connection], object] | None = None


def findings_of(saved: Saved) -> list[Finding]:
    return [Finding(**f) for f in saved["findings"]]


def outcome_step(outcome: Outcome) -> Step:
    return Step(
        "decide",
        outcome.by,
        f"{outcome.status}: {outcome.reason}",
        {"outcome": asdict(outcome)},
    )


def checks(case: Case, saved: Saved, judge: Judge) -> Step:
    findings = run_checks(case)
    summary = ", ".join(f.code for f in findings) or "none"
    return Step(
        "route",
        "rules",
        f"Checks found: {summary}",
        {"findings": [asdict(f) for f in findings]},
    )


def route(case: Case, saved: Saved, judge: Judge) -> Step:
    outcome = triage(findings_of(saved))
    if outcome is None:
        return Step("judge", "rules", "Needs judgement: sent to the model")
    return outcome_step(outcome)


def judgement(case: Case, saved: Saved, judge: Judge) -> Step:
    verdict, name = judge(case, findings_of(saved))
    return Step(
        "guard",
        f"model:{name}",
        f"{verdict.decision} ({verdict.confidence:.2f}, sections "
        f"{verdict.policy_sections}): {verdict.reasons}",
        {"verdict": verdict.model_dump(), "model": name},
    )


def guard(case: Case, saved: Saved, judge: Judge) -> Step:
    verdict = Verdict.model_validate(saved["verdict"])
    return outcome_step(enforce(verdict, case.invoice["total_pence"]))


def decision(case: Case, saved: Saved, judge: Judge) -> Step:
    outcome = Outcome(**saved["outcome"])
    invoice_id = case.invoice["id"]
    return Step(
        "pay" if outcome.status == "approved" else "done",
        outcome.by,
        f"Decided: {outcome.status}",
        write=lambda conn: decide(
            conn, invoice_id, outcome.status, outcome.by, outcome.reason
        ),
    )


def payment(case: Case, saved: Saved, judge: Judge) -> Step:
    invoice_id = case.invoice["id"]
    return Step(
        "done",
        "payments",
        "Paid to the account on file",
        write=lambda conn: pay(conn, invoice_id),
    )


STAGES: dict[str, Callable[[Case, Saved, Judge], Step]] = {
    "checks": checks,
    "route": route,
    "judge": judgement,
    "guard": guard,
    "decide": decision,
    "pay": payment,
}


def advance(conn: sqlite3.Connection, invoice_id: str, owner: str, judge: Judge) -> str:
    """Run the job's current stage, save its checkpoint, and return the next stage."""
    job = conn.execute(
        "SELECT stage, checkpoint FROM jobs WHERE invoice_id = ?", (invoice_id,)
    ).fetchone()
    saved = json.loads(job["checkpoint"])
    step = STAGES[job["stage"]](load_case(conn, invoice_id), saved, judge)
    with transaction(conn):
        held = conn.execute(
            "UPDATE jobs SET stage = ?, checkpoint = ? WHERE invoice_id = ?"
            " AND lease_owner = ?",
            (step.next_stage, json.dumps(saved | step.saved), invoice_id, owner),
        )
        if held.rowcount == 0:
            raise LeaseLostError(invoice_id)
        if step.write:
            step.write(conn)
        log(conn, invoice_id, step.actor, step.message)
    return step.next_stage
