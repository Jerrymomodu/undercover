"""Run the whole queue on a fresh database and score it against the right answers."""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from invoice_desk.db import ROOT, connect, create
from invoice_desk.judge import Judge
from invoice_desk.workers import run_workers

EXPECTED = ROOT / "evals" / "expected.json"


@dataclass(frozen=True)
class Result:
    invoice_id: str
    outcome: str
    accept: list[str]
    by: str
    why: str

    @property
    def passed(self) -> bool:
        return self.outcome in self.accept

    @property
    def critical(self) -> bool:
        """Approving an invoice that should not have been approved: a wrong payment."""
        return self.outcome == "approved" and "approved" not in self.accept


def run_evals(judge: Judge, workers: int, db_path: Path) -> list[Result]:
    """Seed a fresh database, work the queue, and compare each outcome."""
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    create(db_path)
    run_workers(db_path, workers, judge)
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT id, status, decided_by FROM invoices ORDER BY id"
    ).fetchall()
    conn.close()
    return [
        Result(
            invoice_id=r["id"],
            outcome="approved" if r["status"] == "paid" else r["status"],
            accept=expected[r["id"]]["accept"],
            by=r["decided_by"] or "",
            why=expected[r["id"]]["why"],
        )
        for r in rows
    ]


def report(results: list[Result]) -> str:
    """A table of the results and a summary."""
    lines = [f"{'Invoice':<9}{'Outcome':<12}{'Expected':<24}{'By':<8}Result"]
    for r in results:
        mark = "CRITICAL" if r.critical else "pass" if r.passed else "FAIL"
        expected = " or ".join(r.accept)
        lines.append(
            f"{r.invoice_id:<9}{r.outcome:<12}{expected:<24}{r.by:<8}{mark}"
            + ("" if r.passed else f"  ({r.why})")
        )
    passed = sum(r.passed for r in results)
    by = Counter(r.by for r in results)
    lines += [
        "",
        f"Passed {passed} of {len(results)}. Critical errors: "
        f"{sum(r.critical for r in results)}.",
        "Decided by: " + ", ".join(f"{k} {v}" for k, v in sorted(by.items())),
    ]
    return "\n".join(lines)
