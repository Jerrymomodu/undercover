import json
from pathlib import Path

import pytest

from invoice_desk.db import connect, create
from invoice_desk.evals import EXPECTED
from invoice_desk.models import Case, Decision, Finding, Verdict

ANSWERS: dict[str, Decision] = {
    "approved": "approve",
    "rejected": "reject",
    "for_review": "escalate",
}


class OracleJudge:
    """Gives the right answer for every invoice, and counts its calls."""

    def __init__(self, confidence: float = 0.95) -> None:
        self.expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
        self.confidence = confidence
        self.calls: list[str] = []

    def __call__(self, case: Case, findings: list[Finding]) -> tuple[Verdict, str]:
        invoice_id = case.invoice["id"]
        self.calls.append(invoice_id)
        decision = ANSWERS[self.expected[invoice_id]["accept"][0]]
        verdict = Verdict(
            decision=decision,
            confidence=self.confidence,
            reasons="Oracle",
            policy_sections=[9],
        )
        return verdict, "oracle"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "test.db"
    create(path)
    return path


@pytest.fixture
def conn(db: Path):
    connection = connect(db)
    yield connection
    connection.close()


@pytest.fixture
def oracle() -> OracleJudge:
    return OracleJudge()
